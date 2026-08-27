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

        # ── 银行 ──
        bank = CommercialBank(
            id="bank_1",
            reserves=initial_reserves,
            capital=initial_reserves,
            car_requirement=config.car_requirement,
            car_buffer=config.car_buffer,
            loan_rate_base_spread=config.loan_rate_base_spread,
            loan_rate_car_pressure=config.loan_rate_car_pressure,
            deposit_rate_margin=config.deposit_rate_margin,
        )

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
            deposits=initial_firm_deposits,
            debt=initial_firm_deposits,
            depreciation_rate=config.depreciation_rate,
            investment_sensitivity=config.investment_sensitivity,
            calvo_price_prob=config.calvo_price_prob,
            calvo_markup_target=config.calvo_markup_target,
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
        return SimulationState(
            t=0,
            config=config,
            households=households,
            firm=firm,
            bank=bank,
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
