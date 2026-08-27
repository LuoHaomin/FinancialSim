"""SimulationState: 持有所有 agent 引用 + 宏观变量."""
from __future__ import annotations

from dataclasses import dataclass, field

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
    """

    t: int = 0
    config: object | None = None  # SimConfig

    # ── Agents ──
    households: list[Household] = field(default_factory=list)
    firm: Firm | None = None  # Phase 0: 单一聚合企业
    bank: CommercialBank | None = None
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
        """从 agent 状态构造 5 个 BS 对象."""
        assert self.bank is not None
        assert self.government is not None
        assert self.central_bank is not None
        assert self.firm is not None

        return {
            "households": HouseholdBalanceSheet(
                cash=self.total_household_cash(),
                deposits=self.total_household_deposits(),
                # Phase 0: 简化, 只追踪现金 + 存款
            ),
            "firms": FirmBalanceSheet(
                cash=self.firm.cash,
                deposits=self.firm.deposits,
                inventories=self.firm.inventory,
                capital_stock=self.firm.capital,
                bank_loans=self.firm.debt,
            ),
            "banks": CommercialBankBalanceSheet(
                reserves=self.bank.reserves,
                loans_to_firms=self.bank.loans_to_firms,
                loans_to_households=self.bank.loans_to_households,
                gov_bonds_held=self.bank.gov_bonds_held,
                deposits_from_hh=self.bank.deposits_from_hh,
                deposits_from_firms=self.bank.deposits_from_firms,
                capital=self.bank.capital,
            ),
            "government": GovernmentBalanceSheet(
                treasury_deposits=0,  # Phase 0: 政府无独立账户
                other_assets=0,
                bonds_outstanding=self.government.debt,
            ),
            "cb": CentralBankBalanceSheet(
                gov_bonds=self.central_bank.gov_bonds,
                lolr_claims=0,
                other_assets=0,
                bank_reserves=self.central_bank.bank_reserves,
                currency_issued=self.central_bank.currency_issued,
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
