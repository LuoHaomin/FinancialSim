"""Simulation: 顶层仿真类, 编排 tick + 初始化 + SFC."""
from __future__ import annotations

import numpy as np

from financial_sim.agents.central_bank import CentralBank
from financial_sim.agents.commercial_bank import CommercialBank
from financial_sim.agents.firm import Firm
from financial_sim.agents.government import Government
from financial_sim.agents.household import Household
from financial_sim.config import SimConfig
from financial_sim.core.state import SimulationState
from financial_sim.core.step import monthly_tick
from financial_sim.expectations.inflation import InflationExpectation
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

    def __init__(self, config: SimConfig | None = None, seed: int | None = None) -> None:
        self.config = config or SimConfig.default()
        self.seed = seed if seed is not None else self.config.seed
        self.rng = RNGManager(seed=self.seed)
        self.state = self._build_state(self.config)
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
        """构造初始 SFC-balanced state, 家庭参数走命名随机流."""
        n_hh = config.n_households
        h_rng = self.rng.stream("household_init")

        # ── 央行 ──
        cb = CentralBank(
            policy_rate=config.cb_policy_rate_initial,
            neutral_rate=config.cb_neutral_rate,
            target_inflation=config.target_inflation,
            taylor_inflation_coeff=config.taylor_inflation_coeff,
            taylor_output_coeff=config.taylor_output_coeff,
        )
        initial_reserves = float(n_hh) * 10  # 每个家庭 10 单位
        cb.gov_bonds = initial_reserves
        cb.bank_reserves = initial_reserves

        # ── 银行 (Phase 2: 多家 + 同业网络) ──
        n_banks = max(1, int(getattr(config, "n_banks", 1)))
        banks: list[CommercialBank] = []
        # 平分初始准备金给各银行 (保持 SFC)
        per_bank_reserves = initial_reserves / n_banks
        per_bank_capital = initial_reserves / n_banks
        for b_idx in range(n_banks):
            bank = CommercialBank(
                id=f"bank_{b_idx + 1}",
                tier=1 if b_idx < int(getattr(config, "interbank_core_size", 3)) else 2,
                reserves=per_bank_reserves,
                capital=per_bank_capital,
                car_requirement=config.car_requirement,
                car_buffer=config.car_buffer,
                loan_rate_base_spread=config.loan_rate_base_spread,
                loan_rate_car_pressure=config.loan_rate_car_pressure,
                deposit_rate_margin=config.deposit_rate_margin,
                mortgage_rate_spread=getattr(config, "housing_mortgage_rate_spread", 0.02),
            )
            banks.append(bank)

        # 同业网络 (Phase 2)
        interbank: InterbankNetwork | None = None
        if n_banks > 1:
            nw_rng = self.rng.stream("interbank_init")
            interbank = InterbankNetwork.build_core_periphery(
                bank_ids=[b.id for b in banks],
                core_size=int(getattr(config, "interbank_core_size", 3)),
                link_density=float(getattr(config, "interbank_link_density", 0.5)),
                avg_exposure=initial_reserves * 0.05 / max(1, n_banks),
                rng=nw_rng,
            )
            # 把敞口记到各银行账目
            for (creditor_id, debtor_id), amount in interbank.exposures.items():
                creditor = next(b for b in banks if b.id == creditor_id)
                debtor = next(b for b in banks if b.id == debtor_id)
                creditor.interbank_claims += amount
                debtor.interbank_debt += amount

        # 主银行引用: 恒为 banks[0] (主银行语义).
        # 多银行时所有"面向部门聚合"的资金流 (工资/消费/政府/税收) 都记在
        # banks[0]; 其余银行只参与同业网络与逐银行政策. 聚合视图由
        # build_balance_sheets 现场求和, 不再维护虚拟代理对象.
        bank = banks[0]

        # ── 政府 ──
        government = Government(
            debt=initial_reserves,
            gov_spending=config.gov_spending_monthly if config.fiscal_enabled else 0.0,
            transfers=0.0,
            interest_rate=config.cb_policy_rate_initial,
        )

        # ── 企业 ──
        wage = 1.0
        initial_firm_deposits = float(n_hh) * wage * 2  # 首月工资 + 缓冲
        bank.loans_to_firms = initial_firm_deposits
        bank.deposits_from_firms = initial_firm_deposits
        firm = Firm(
            id="firm_0",
            sector="consumer_goods",
            productivity=1.0,
            price=1.0,
            wage_offered=wage,
            employees=n_hh,
            baseline_employees=n_hh,        # 摩擦雇佣目标 = 稳态全员
            deposits=initial_firm_deposits,
            debt=initial_firm_deposits,
            depreciation_rate=config.depreciation_rate,
            investment_sensitivity=config.investment_sensitivity,
            calvo_price_prob=config.calvo_price_prob,
            calvo_markup_target=config.calvo_markup_target,
            default_equity_threshold=getattr(
                config, "firm_default_equity_threshold", 0.0
            ),
        )

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

        # 异质存款必须与银行账目镜像 (SFC check: HH 存款 = bank.deposits_from_hh)
        hh_total_deposits = sum(h.deposits for h in households)
        bank.deposits_from_hh += hh_total_deposits
        bank.reserves += hh_total_deposits
        cb.bank_reserves += hh_total_deposits
        cb.gov_bonds += hh_total_deposits  # CB 再购等额国债为注入提供资产
        government.debt += hh_total_deposits

        # ── 构造 state ──
        # ── Phase 1+: 事件系统 (从 config.preset_shocks 自动装配) ──
        em: EventManager | None = None
        if bool(getattr(config, "enable_events", True)) and getattr(
            config, "preset_shocks", None
        ):
            em = build_event_manager(config.preset_shocks)

        # ── Phase 2: 住房市场 ──
        housing = HousingMarket.from_config(config) if bool(
            getattr(config, "enable_housing", True)
        ) else None
        if housing is not None:
            # 初始化家庭住房持有: 一户一套自住房 (全款, 无房贷)
            # 简化: 房屋视为"已存在的资产", 不通过银行账目融资
            # 房贷机制仅在 _mortgage_default_check 中以"动态发放"形式出现
            for h in households:
                h.housing_units = 1
                h.mortgage_balance = 0.0  # 初始无房贷
                h.mortgage_rate = (
                    config.cb_policy_rate_initial
                    + housing.mortgage_rate_spread
                )

            # 给一部分家庭 (按存款分布) 发放初始抵押贷款, 以启动 mortgage channel
            # 资金来源: 银行用 CB 注入的准备金发放 (SFC-balanced)
            initial_mortgage_ltv = float(
                getattr(config, "housing_initial_ltv", 0.70)
            )
            total_mortgages = 0.0
            # 选择存款较多的一半家庭 (按存款降序)
            sorted_hh = sorted(
                households, key=lambda h: h.deposits, reverse=True
            )
            eligible = sorted_hh[: n_hh // 2]
            for h in eligible:
                mortgage = housing.price * initial_mortgage_ltv
                h.mortgage_balance = mortgage
                # HH 拿到现金 (买房首付已被假设支付, 现金进入存款)
                # 这里简化为: mortgage 直接进 HH 存款 (隐含"再融资"提取)
                h.deposits += mortgage
                total_mortgages += mortgage

            # 银行端镜像 (SFC 严格分账)
            # 机制: CB 通过 OMO 向银行注入准备金 → 银行获得资金发放贷款
            #   bank.A += reserves (从 CB); bank.A += loans_to_hh; bank.L += deposits
            #   → bank.A - bank.L - bank.capital 必须守恒
            # 解法: 注入时 bank.capital 同步增加 (CB 的资本注入, 类似 QE)
            if banks and total_mortgages > 0:
                bank0 = banks[0]
                bank0.loans_to_households = total_mortgages
                # CB OMO: 准备金注入 + 等额资本注入 (SFC 平衡)
                cb.gov_bonds += total_mortgages
                cb.bank_reserves += total_mortgages
                bank0.reserves += total_mortgages
                bank0.capital += total_mortgages  # 关键: 资本同步增
                # HH 存款增加 → bank.deposits_from_hh 同步增加
                bank0.deposits_from_hh += total_mortgages
                # 政府债务 (OMO 购债 = 政府"卖给"CB)
                government.debt += total_mortgages

        return SimulationState(
            t=0,
            config=config,
            households=households,
            firm=firm,
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
