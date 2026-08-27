"""SimulationState: 持有所有 agent 引用 + 宏观变量."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from financial_sim.agents.central_bank import CentralBank
from financial_sim.agents.commercial_bank import CommercialBank
from financial_sim.agents.firm import Firm
from financial_sim.agents.government import Government
from financial_sim.agents.household import Household
from financial_sim.expectations.inflation import InflationExpectation
from financial_sim.monetary.balance_sheets import (
    CentralBankBalanceSheet,
    CommercialBankBalanceSheet,
    FirmBalanceSheet,
    GovernmentBalanceSheet,
    HouseholdBalanceSheet,
)
from financial_sim.utils.logging import get_logger

if TYPE_CHECKING:
    from financial_sim.markets.bonds import BondMarket
    from financial_sim.markets.housing import HousingMarket
    from financial_sim.network.interbank import InterbankNetwork

logger = get_logger(__name__)


@dataclass
class MacroSnapshot:
    """某一 tick 的宏观状态."""

    t: int
    real_gdp: float
    nominal_gdp: float
    inflation_yoy: float
    unemployment_rate: float
    policy_rate: float
    avg_wage: float
    total_consumption: float
    total_output: float


@dataclass
class SimulationState:
    """仿真状态: 所有 agent + 宏观变量 + 历史.

    Phase 0 简化为:
    - 1 个部门
    - 1 家聚合银行
    - 1 个政府
    - 1 个央行
    - N 个家庭 (个体级)
    - 1 个聚合企业 (Phase 1 改为多部门多企业)

    Phase 2: 多银行 + 住房市场 + 同业网络.
    """

    t: int = 0
    config: object | None = None  # SimConfig

    # ── Agents ──
    households: list[Household] = field(default_factory=list)
    firm: Firm | None = None  # Phase 0: 单一聚合企业
    bank: CommercialBank | None = None  # 主银行 (n_banks=1 时为唯一银行, 否则聚合代理)
    banks: list[CommercialBank] = field(default_factory=list)  # Phase 2: 全部银行
    government: Government | None = None
    central_bank: CentralBank | None = None

    # ── 宏观变量 ──
    real_gdp: float = 0.0
    nominal_gdp: float = 0.0
    inflation_yoy: float = 0.02  # 年化
    unemployment_rate: float = 0.0
    potential_gdp: float = 1000.0
    output_gap: float = 0.0

    # ── Phase 1: 价格水平 / 预期 / 随机源 ──
    price_level: float = 1.0
    price_level_history: list[float] = field(default_factory=list)
    last_month_sales: float = 0.0  # 上月实际销量 (商品市场定价基准)
    inflation_expectation: InflationExpectation = field(
        default_factory=InflationExpectation
    )
    rng_manager: object | None = None  # simulation.rng.RNGManager

    # ── Phase 1+: 事件系统 (ShockEvent) ──
    event_manager: object | None = None  # simulation.events.EventManager
    shock_log: list[dict] = field(default_factory=list)  # 已触发的冲击记录

    # ── 冲击瞬时覆盖 (one-shot 风格, 每月 step 读取) ──
    _gov_spending_multiplier: float = 1.0
    _income_tax_rate_override: float | None = None

    # ── Phase 2: 住房市场 + 同业网络 ──
    housing_market: HousingMarket | None = None
    interbank_network: InterbankNetwork | None = None
    housing_price: float = 200.0          # 房价镜像 (供便捷访问)

    # ── Phase 3 前置 P0-b: 债券市场 ──
    bond_market: BondMarket | None = None
    monthly_interest_paid: float = 0.0     # 当月付息累计 (教学诊断)
    housing_price_history: list[float] = field(default_factory=list)
    housing_expectations_factor: float = 1.0  # 房价泡沫因子 (>1 = 投机性溢价)
    fire_sale_pressure: float = 0.0      # 当前 fire-sale 强度 (0-1)
    failed_banks: list[str] = field(default_factory=list)  # 已失败银行 ID

    # ── 历史 (用于分析与绘图) ──
    macro_history: list[MacroSnapshot] = field(default_factory=list)

    # ── SFC 错误累计 (调试用) ──
    sfc_violations: list[list[str]] = field(default_factory=list)

    # ════════════════════════════════════════════════════
    # 派生方法
    # ════════════════════════════════════════════════════

    def total_labor_force(self) -> int:
        return len(self.households)

    def total_employed(self) -> int:
        return sum(1 for h in self.households if h.employed)

    def total_unemployed(self) -> int:
        return sum(1 for h in self.households if not h.employed)

    def unemployment_rate_calc(self) -> float:
        n = self.total_labor_force()
        if n == 0:
            return 0.0
        return self.total_unemployed() / n

    def avg_wage(self) -> float:
        employed = [h for h in self.households if h.employed]
        if not employed:
            return 0.0
        return sum(h.wage for h in employed) / len(employed)

    def total_consumption(self) -> float:
        return sum(h.decide_consumption() for h in self.households)

    def total_savings(self) -> float:
        return sum(h.decide_savings() for h in self.households)

    def total_income(self) -> float:
        return sum(h.income for h in self.households)

    def total_output(self) -> float:
        if self.firm is None:
            return 0.0
        return self.firm.production()

    def total_household_deposits(self) -> float:
        return sum(h.deposits for h in self.households)

    def total_household_cash(self) -> float:
        return sum(h.cash for h in self.households)

    # ════════════════════════════════════════════════════
    # 构造 BS 对象 (供 SFC 校验)
    # ════════════════════════════════════════════════════

    def build_balance_sheets(self) -> dict[str, object]:
        """从 agent 状态构造 5 个 BS 对象.

        Phase 2: 多家银行聚合成单个 BS 校验 (跨部门 SFC).
        """
        assert self.bank is not None
        assert self.government is not None
        assert self.central_bank is not None
        assert self.firm is not None

        # 聚合所有银行的余额 (兼容 n_banks=1 和 n_banks>1)
        if self.banks:
            reserves = sum(b.reserves for b in self.banks)
            loans_to_firms = sum(b.loans_to_firms for b in self.banks)
            loans_to_households = sum(b.loans_to_households for b in self.banks)
            gov_bonds_held = sum(b.gov_bonds_held for b in self.banks)
            interbank_claims = sum(b.interbank_claims for b in self.banks)
            reo_value = sum(b.reo_value for b in self.banks)
            deposits_from_hh = sum(b.deposits_from_hh for b in self.banks)
            deposits_from_firms = sum(b.deposits_from_firms for b in self.banks)
            interbank_debt = sum(b.interbank_debt for b in self.banks)
            lolr_debt = sum(b.lolr_debt for b in self.banks)
            capital = sum(b.capital for b in self.banks)
        else:
            # 兼容: 单银行 (Phase 0/1)
            reserves = self.bank.reserves
            loans_to_firms = self.bank.loans_to_firms
            loans_to_households = self.bank.loans_to_households
            gov_bonds_held = self.bank.gov_bonds_held
            interbank_claims = 0.0
            reo_value = self.bank.reo_value
            deposits_from_hh = self.bank.deposits_from_hh
            deposits_from_firms = self.bank.deposits_from_firms
            interbank_debt = 0.0
            lolr_debt = 0.0
            capital = self.bank.capital

        housing_price = self.housing_market.price if self.housing_market else 0.0

        return {
            "households": HouseholdBalanceSheet(
                cash=self.total_household_cash(),
                deposits=self.total_household_deposits(),
                bonds=sum(h.bonds for h in self.households),
                housing_self=housing_price * sum(
                    min(1, h.housing_units) for h in self.households
                ),
                housing_investment=housing_price * sum(
                    max(0, h.housing_units - 1) for h in self.households
                ),
                mortgage=sum(h.mortgage_balance for h in self.households),
                consumer_loan=sum(h.consumer_loan for h in self.households),
            ),
            "firms": FirmBalanceSheet(
                cash=self.firm.cash,
                deposits=self.firm.deposits,
                inventories=self.firm.inventory,
                capital_stock=self.firm.capital,
                bank_loans=self.firm.debt,
            ),
            "banks": CommercialBankBalanceSheet(
                reserves=reserves,
                loans_to_firms=loans_to_firms,
                loans_to_households=loans_to_households,
                gov_bonds_held=gov_bonds_held,
                interbank_claims=interbank_claims,
                reo_value=reo_value,
                deposits_from_hh=deposits_from_hh,
                deposits_from_firms=deposits_from_firms,
                interbank_debt=interbank_debt,
                capital=capital,
            ),
            "government": GovernmentBalanceSheet(
                treasury_deposits=self.government.treasury_deposits,
                other_assets=self.government.other_assets,
                bonds_outstanding=self.government.debt,
            ),
            "cb": CentralBankBalanceSheet(
                gov_bonds=self.central_bank.gov_bonds,
                lolr_claims=lolr_debt,  # CB 视角: 银行的 LOLR 借款是 CB 资产
                other_assets=0,
                bank_reserves=self.central_bank.bank_reserves,
                currency_issued=self.central_bank.currency_issued,
                treasury_deposits=self.central_bank.treasury_deposits,
                capital=self.central_bank.capital,
            ),
        }

    def snapshot_macro(self) -> None:
        """记录当前 tick 的宏观状态."""
        snap = MacroSnapshot(
            t=self.t,
            real_gdp=self.real_gdp,
            nominal_gdp=self.nominal_gdp,
            inflation_yoy=self.inflation_yoy,
            unemployment_rate=self.unemployment_rate,
            policy_rate=self.central_bank.policy_rate if self.central_bank else 0.0,
            avg_wage=self.avg_wage(),
            total_consumption=self.total_consumption(),
            total_output=self.total_output(),
        )
        self.macro_history.append(snap)
