"""Simulation: 顶层仿真类, 编排 tick + 初始化 + SFC."""
from __future__ import annotations

from financial_sim.agents.central_bank import CentralBank
from financial_sim.agents.commercial_bank import CommercialBank
from financial_sim.agents.firm import Firm
from financial_sim.agents.government import Government
from financial_sim.agents.household import Household
from financial_sim.config import SimConfig
from financial_sim.core.state import SimulationState
from financial_sim.core.step import monthly_tick
from financial_sim.utils.logging import get_logger

logger = get_logger(__name__)


class Simulation:
    """Phase 0 仿真入口.

    使用:
        config = SimConfig.default()
        sim = Simulation(config)
        sim.run(n_ticks=12)
        print(sim.state.real_gdp)
    """

    def __init__(self, config: SimConfig | None = None) -> None:
        self.config = config or SimConfig.default()
        self.state = self._build_state(self.config)
        logger.info(
            f"Simulation initialized: "
            f"{len(self.state.households)} HHs, "
            f"1 firm, 1 bank, "
            f"policy_rate={self.state.central_bank.policy_rate:.3f}"
        )

    # ════════════════════════════════════════════════════════════
    # 初始化 (SFC-balanced)
    # ════════════════════════════════════════════════════════════
    def _build_state(self, config: SimConfig) -> SimulationState:
        """构造初始 SFC-balanced state.

        初始时, 所有家庭就业, 1 家聚合企业, 平衡预算政府, 央行 + 银行已建立.

        初始资金流:
        - 政府发行 X 国债 → CB 买入 → CB 创造准备金 X → 银行收到准备金
        - 银行初始资本 X (来自 CB 的 "equity infusion")
        - 银行借 Y 给企业 → 企业获得 Y 存款
        - 企业用存款支付工资
        """
        n_hh = config.n_households

        # ── 央行 ──
        cb = CentralBank(
            policy_rate=config.cb_policy_rate_initial,
            neutral_rate=config.cb_neutral_rate,
            target_inflation=config.target_inflation,
        )
        # CB 创造初始准备金 (通过 OMO 买入政府债)
        initial_reserves = float(n_hh) * 10  # 每个家庭 10 单位
        cb.gov_bonds = initial_reserves
        cb.bank_reserves = initial_reserves
        # CB cap = 0 (SFC: A=gov_bonds = L=bank_reserves)

        # ── 银行 ──
        # 收到准备金后, 初始资本 = 准备金 (equity infusion from CB)
        bank = CommercialBank(
            id="bank_1",
            reserves=initial_reserves,
            capital=initial_reserves,  # A=reserves, L=0, cap=reserves
        )

        # ── 政府 ──
        # 初始时已发行国债 (被 CB 持有)
        government = Government(
            debt=initial_reserves,
            gov_spending=200.0,
            transfers=50.0,
            interest_rate=config.cb_policy_rate_initial,  # 国债利率 = 政策利率
        )

        # ── 企业 ──
        # 从银行借款, 获得初始存款 (用以支付首月工资)
        wage = 1.0
        initial_firm_deposits = float(n_hh) * wage  # 足够支付 1 个月工资
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
        )

        # ── 家庭 ──
        households = [
            Household(
                id=f"h_{i:04d}",
                sector="consumer_goods",
                wage=wage,
                cash=0.0,
                deposits=0.0,
                savings_rate=0.3,
                mpc=0.7,
            )
            for i in range(n_hh)
        ]

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
            potential_gdp=float(n_hh),  # 稳态 GDP = 1 单位/人
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
                    f"unemp={self.state.unemployment_rate:.2%}, "
                    f"SFC_violations={sum(len(v) for v in self.state.sfc_violations)}"
                )
        return self.state

    # ════════════════════════════════════════════════════════════
    # 便捷方法
    # ════════════════════════════════════════════════════════════
    def reset(self) -> None:
        """重置到初始状态."""
        self.state = self._build_state(self.config)
