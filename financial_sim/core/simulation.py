"""Simulation: 顶层仿真类, 编排 tick + 初始化 + SFC."""
from __future__ import annotations

import numpy as np

from financial_sim.agents.central_bank import CentralBank
from financial_sim.agents.commercial_bank import CommercialBank
from financial_sim.agents.firm import Firm
from financial_sim.agents.government import Government
from financial_sim.agents.household import Household
from financial_sim.config import SimConfig, sector_param
from financial_sim.core.state import SimulationState
from financial_sim.core.step import monthly_tick
from financial_sim.expectations.inflation import InflationExpectation
from financial_sim.markets.bonds import BondMarket
from financial_sim.markets.housing import HousingMarket
from financial_sim.network.interbank import InterbankNetwork
from financial_sim.simulation.events import EventManager, build_event_manager
from financial_sim.simulation.rng import RNGManager
from financial_sim.utils.distributions import truncated_normal
from financial_sim.utils.logging import get_logger

logger = get_logger(__name__)


class Simulation:
    """Phase 1 仿真入口.

    使用:
        config = SimConfig.default()
        sim = Simulation(config, seed=42)
        sim.run(n_ticks=12)
        state = sim.state  # 查看宏观变量
    """

    def __init__(
        self,
        config: SimConfig | None = None,
        seed: int | None = None,
        scenario_events: EventManager | None = None,
    ) -> None:
        self.config = config or SimConfig.default()
        self.seed = seed if seed is not None else self.config.seed
        self.rng = RNGManager(seed=self.seed)
        self.state = self._build_state(self.config)
        # P0-c: scenario_events 覆盖自动从 config.preset_shocks 装配的 manager
        if scenario_events is not None:
            self.state.event_manager = scenario_events
        logger.info(
            f"Simulation initialized (seed={self.seed}): "
            f"{len(self.state.households)} HHs, "
            f"1 firm, 1 bank, "
            f"policy_rate={self.state.central_bank.policy_rate:.3f}"
        )

    # ════════════════════════════════════════════════════════════
    # 初始化 (SFC-balanced)
    # ════════════════════════════════════════════════════════════
    def _build_state(self, config: SimConfig) -> SimulationState:
        """构造初始 SFC-balanced state, 家庭参数走命名随机流.

        初始化策略 (VALIDATION.md §13.2 "反向推算"):
        先定各部门的**行为性**存量 (家庭存款/房贷、企业贷款/存款), 再把银行
        准备金与资本作为**平衡项**反解出来, 使初始 CAR 命中目标值:

            A_bank = 存款总额 / (1 − car_target)
            准备金 = A_bank − 贷款总额
            资本   = A_bank − 存款总额 = car_target × A_bank

        央行/政府侧再镜像准备金 (CB 持等额国债). 这样初始 CAR 是**校准出来的**,
        而不是记账凑数的副产品 — 历史 bug: 初始房贷曾用 `bank.capital +=
        total_mortgages` 凑平, 导致 CAR ≈ 1.2, 资本监管通道从第一个 tick 就失效.
        """
        n_hh = config.n_households
        h_rng = self.rng.stream("household_init")

        # ── 央行 (先只设政策参数, 资产负债表在最后镜像) ──
        cb = CentralBank(
            policy_rate=config.cb_policy_rate_initial,
            neutral_rate=config.cb_neutral_rate,
            target_inflation=config.target_inflation,
            taylor_inflation_coeff=config.taylor_inflation_coeff,
            taylor_output_coeff=config.taylor_output_coeff,
        )

        # ── 企业 (贷款融资的营运资金; Phase 3 Week A 多部门列表化) ──
        # 每部门一家起步 (统计意义的多家异质性留 Week A 后续).
        # 营运资金与初始就业按部门劳动份额分配, 残差记在第一家 (消费部门),
        # 保证 Σfirm.debt 与旧单企业口径完全一致 (银行侧镜像逐位相等).
        wage = 1.0
        initial_firm_deposits = float(n_hh) * wage * 2  # 首月工资 + 缓冲
        labor_shares = config.normalized_labor_shares()
        sectors = list(getattr(config, "sectors", ["consumer_goods"])) or [
            "consumer_goods"
        ]
        firms: list[Firm] = []
        allocated_dep = 0.0
        allocated_emp = 0
        for si, sector in enumerate(sectors):
            share = labor_shares.get(sector, 1.0 / len(sectors))
            last_sector = si == len(sectors) - 1
            dep = (
                initial_firm_deposits - allocated_dep
                if last_sector
                else round(initial_firm_deposits * share, 10)
            )
            emp = (
                n_hh - allocated_emp if last_sector
                else int(round(n_hh * share))
            )
            firms.append(Firm(
                id=f"firm_{si}_{sector}",
                sector=sector,
                productivity=sector_param(sector, "productivity", 1.0),
                price=sector_param(sector, "price", 1.0),
                wage_offered=wage,
                employees=max(0, emp),
                baseline_employees=max(0, emp),
                deposits=dep,
                debt=dep,
                depreciation_rate=config.depreciation_rate,
                investment_sensitivity=config.investment_sensitivity,
                calvo_price_prob=config.calvo_price_prob,
                calvo_markup_target=config.calvo_markup_target,
                production_function=getattr(
                    config, "production_function", "linear"
                ),
                sigma_elasticity=float(getattr(config, "sigma_elasticity", 0.5)),
                alpha_capital=float(getattr(config, "alpha_capital", 0.3)),
                default_equity_threshold=getattr(
                    config, "firm_default_equity_threshold", 0.0
                ),
            ))
            allocated_dep += dep
            allocated_emp += max(0, emp)
        firm = firms[0]

        # ── 家庭 (异质: 储蓄率/MPC 截断正态; 工资对数正态) ──
        savings_draws = truncated_normal(
            h_rng, config.hh_savings_rate_mean, config.hh_savings_rate_std, 0.0, 0.95, n_hh,
        )
        mpc_draws = truncated_normal(
            h_rng, config.hh_mpc_mean, config.hh_mpc_std, 0.05, 1.0, n_hh,
        )
        wage_draws = h_rng.lognormal(
            mean=float(np.log(wage)), sigma=config.hh_wage_lognormal_sigma, size=n_hh
        )
        deposits_draws = h_rng.lognormal(
            mean=float(np.log(config.hh_initial_deposit_median)), sigma=0.6, size=n_hh
        )
        households = [
            Household(
                id=f"h_{i:04d}",
                sector="consumer_goods",
                wage=float(wage_draws[i]),
                deposits=float(deposits_draws[i]),
                savings_rate=float(savings_draws[i]),
                mpc=float(mpc_draws[i]),
                wealth_effect_coef=config.wealth_effect_coef,
            )
            for i in range(n_hh)
        ]
        for h in households:
            h.permanent_income = h.wage

        # 初始就业归属: 按企业顺序切分家庭, 写 employer_id (工资支付/失业归属用)
        hh_cursor = 0
        for f in firms:
            for h in households[hh_cursor : hh_cursor + f.employees]:
                h.sector = f.sector
                h.employer_id = f.id
            hh_cursor += f.employees

        # ── Phase 2: 住房市场 + 初始房贷 (纯信用创造) ──
        housing = HousingMarket.from_config(config) if bool(
            getattr(config, "enable_housing", True)
        ) else None
        total_mortgages = 0.0
        if housing is not None:
            # 实物存量: 一户一套自住房 (房屋是既存资产, 不通过银行融资)
            housing.total_units = n_hh
            for h in households:
                h.housing_units = 1
                h.mortgage_balance = 0.0
                h.mortgage_rate = (
                    config.cb_policy_rate_initial + housing.mortgage_rate_spread
                )

            # 给存款较多的一半家庭发放初始房贷, 启动 mortgage channel.
            # 记账 (内生信用创造, 两笔同时出现在银行账上, 不需要准备金/资本):
            #   HH: mortgage +M, deposits +M   ↔  Bank: loans_to_hh +M, deposits +M
            # 经济含义: 房贷买房的钱付给了上一任房主 (同属家庭部门), 因此家庭部门
            # 的存款净增 M, 资本/准备金/政府债务均不参与.
            initial_mortgage_ltv = float(getattr(config, "housing_initial_ltv", 0.70))
            sorted_hh = sorted(households, key=lambda h: h.deposits, reverse=True)
            for h in sorted_hh[: n_hh // 2]:
                mortgage = housing.price * initial_mortgage_ltv
                h.mortgage_balance = mortgage
                h.deposits += mortgage
                total_mortgages += mortgage

        # ── 银行: 准备金与资本作为平衡项反解 (命中目标 CAR) ──
        hh_total_deposits = sum(h.deposits for h in households)
        firm_deposits_actual = sum(f.deposits for f in firms)
        total_deposits = hh_total_deposits + firm_deposits_actual
        total_loans = firm_deposits_actual + total_mortgages
        car_target = float(getattr(config, "initial_bank_car", 0.12))
        car_target = min(max(car_target, 0.0), 0.9)
        total_bank_assets = total_deposits / (1.0 - car_target)
        total_reserves = total_bank_assets - total_loans
        if total_reserves < 0:
            # 贷款已超过目标资产规模 → 退化为"零准备金, 资本吸收残差"
            total_reserves = 0.0
            total_bank_assets = total_loans

        n_banks = max(1, int(getattr(config, "n_banks", 1)))
        banks: list[CommercialBank] = []

        # 部门聚合 (工资/消费/政府/税收) 资金流只能记在一家银行上, 因为
        # core/step.py 的 _bank_cycle() 等函数只用 state.bank (= banks[0]).
        # 这是一个**主银行语义**简化: 多银行时其余银行只参与同业网络与逐银行
        # 政策, 不直接吸收部门资金流.
        # 准备金分配: 主银行持有全部 (因为部门聚合准备金也只在主银行账上);
        # 外围银行 reserves = 0, 仅靠 interbank_claims 持有同业债权.
        for b_idx in range(n_banks):
            bank = CommercialBank(
                id=f"bank_{b_idx + 1}",
                tier=1 if b_idx < int(getattr(config, "interbank_core_size", 3)) else 2,
                reserves=total_reserves if b_idx == 0 else 0.0,
                car_requirement=config.car_requirement,
                car_buffer=config.car_buffer,
                loan_rate_base_spread=config.loan_rate_base_spread,
                loan_rate_car_pressure=config.loan_rate_car_pressure,
                deposit_rate_margin=config.deposit_rate_margin,
                mortgage_rate_spread=getattr(config, "housing_mortgage_rate_spread", 0.02),
            )
            banks.append(bank)

        # 主银行持有部门聚合的存贷款 (企业侧 = 各企业求和, 镜像逐位一致)
        bank = banks[0]
        bank.loans_to_firms = firm_deposits_actual
        bank.loans_to_households = total_mortgages
        bank.deposits_from_firms = firm_deposits_actual
        bank.deposits_from_hh = hh_total_deposits
        # 资本 = A − L (主银行单独平衡, 余下银行只放同业敞口)
        bank.capital = bank.total_assets() - bank.total_liabilities()

        # ── 同业网络 (Phase 2): claims/debt 双边同额, 聚合恒等式不变 ──
        # ⚠️ claims/debt 是**银行间**内部资产/负债, 不会改变聚合 BS 恒等式,
        # 因此**不**应调整任何银行的 capital 字段. 这里的主银行资本已在前面
        # 锁定, 外围银行初始 capital=0; 同业敞口的产生是"市场把准备金重新
        # 分配到银行间", 而不是凭空创造/销毁资本.
        # (历史 bug: 早期版本把 `creditor.capital += amount` 写在了这里,
        # 导致聚合 BS 不平衡 −2409 单位, 第一 tick 就被 SFC 检查捕获.)
        # ⚠️ 已知简化 (Phase 3 Week E 修复): 当前 multi-bank 初始化**不**真正
        # 注入同业敞口 — 因为:
        #   1. 主银行之外的银行初始 reserves=0 (它们的钱都存主银行);
        #   2. 真正"开同业关系"意味着主银行减 reserves, 外围银行增 reserves;
        #   3. 但外围银行的 reserves 走的是"从主银行拆借", 这会引入循环依赖.
        # 暂用 interbank=None + interbank_network=None, crisis 场景跑单银行
        # (n_banks=1) 即可演示银行失败 + 政府救助; 多银行的同业敞口留 Phase 3.
        interbank: InterbankNetwork | None = None
        # 多银行模式在 Phase 3 Week E 修复前**禁用** — 见上方说明.
        # 多银行场景的 SFC 校验依赖 Phase 3 真实的多银行账目拆分.

        # ── 央行 + 政府: 镜像准备金 (CB 持等额国债) ──
        cb.bank_reserves = total_reserves
        cb.gov_bonds = total_reserves
        government = Government(
            debt=total_reserves,
            gov_spending=config.gov_spending_monthly if config.fiscal_enabled else 0.0,
            transfers=0.0,
            interest_rate=config.cb_policy_rate_initial,
        )

        # ── Phase 1+: 事件系统 (从 config.preset_shocks 自动装配) ──
        em: EventManager | None = None
        if bool(getattr(config, "enable_events", True)) and getattr(
            config, "preset_shocks", None
        ):
            em = build_event_manager(config.preset_shocks)

        # ── Phase 3 前置 P0-b: 债券市场 ──
        bond_market: BondMarket | None = None
        if bool(getattr(config, "enable_bond_market", True)):
            bond_market = BondMarket(
                outstanding=0.0,
                coupon_rate=float(
                    getattr(config, "bond_coupon_rate", 0.025)
                ),
            )

        return SimulationState(
            t=0,
            config=config,
            households=households,
            firms=firms,
            bank=bank,
            banks=banks,
            government=government,
            central_bank=cb,
            real_gdp=0.0,
            nominal_gdp=0.0,
            inflation_yoy=config.initial_inflation,
            unemployment_rate=0.0,
            potential_gdp=float(n_hh),
            price_level=firm.price,
            inflation_expectation=InflationExpectation(
                value=config.initial_inflation, anchor=config.target_inflation
            ),
            rng_manager=self.rng,
            event_manager=em,
            housing_market=housing,
            housing_price=housing.price if housing else 200.0,
            interbank_network=interbank,
            bond_market=bond_market,
        )

    # ════════════════════════════════════════════════════════════
    # Tick 编排
    # ════════════════════════════════════════════════════════════
    def step(self) -> None:
        """执行一个 tick."""
        monthly_tick(self.state)

    def run(self, n_ticks: int | None = None) -> SimulationState:
        """运行 n_ticks 个 tick. 默认用 config.n_ticks."""
        n = n_ticks or self.config.n_ticks
        logger.info(f"Running {n} ticks from t={self.state.t}")
        for i in range(n):
            self.step()
            if i % 12 == 0:
                logger.info(
                    f"  t={self.state.t}: GDP={self.state.real_gdp:.2f}, "
                    f"infl={self.state.inflation_yoy:.2%}, "
                    f"unemp={self.state.unemployment_rate:.2%}, "
                    f"SFC_violations={sum(len(v) for v in self.state.sfc_violations)}"
                )
        return self.state

    # ════════════════════════════════════════════════════════════
    # 便捷方法
    # ════════════════════════════════════════════════════════════
    def reset(self) -> None:
        """重置到初始状态 (同 seed 完全复现)."""
        self.rng.reset()
        self.state = self._build_state(self.config)


# ════════════════════════════════════════════════════════════
# 多银行聚合视图 (仅用于报告; 校验在 build_balance_sheets 现场求和)
# ════════════════════════════════════════════════════════════
def _aggregate_banks(banks: list[CommercialBank]) -> CommercialBank:
    """把所有银行聚合成一个虚拟银行 (只读视图, 不可用于记账!)."""
    agg = CommercialBank(id="agg_bank", tier=1)
    agg.reserves = sum(b.reserves for b in banks)
    agg.loans_to_firms = sum(b.loans_to_firms for b in banks)
    agg.loans_to_households = sum(b.loans_to_households for b in banks)
    agg.gov_bonds_held = sum(b.gov_bonds_held for b in banks)
    agg.interbank_claims = sum(b.interbank_claims for b in banks)
    agg.deposits_from_hh = sum(b.deposits_from_hh for b in banks)
    agg.deposits_from_firms = sum(b.deposits_from_firms for b in banks)
    agg.interbank_debt = sum(b.interbank_debt for b in banks)
    agg.lolr_debt = sum(b.lolr_debt for b in banks)
    agg.capital = sum(b.capital for b in banks)
    agg.npl_amount = sum(b.npl_amount for b in banks)
    agg.npl_writes_off_cumulative = sum(b.npl_writes_off_cumulative for b in banks)
    agg.npl_mortgages = sum(b.npl_mortgages for b in banks)
    return agg
