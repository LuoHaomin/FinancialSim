"""Labor market: search-matching with frictional unemployment.

Phase 1+ 设计 (AGENTS.md §3.2.4 + MARKETS.md):
- 默认行为: 摩擦失业 (search-matching)
  - 外生月度离职率 labor_separation_rate (默认 1%/月)
  - 岗位空缺 V = max(0, desired − current)
  - 匹配函数 f(θ) = 1 − exp(−η·θ), θ = V/U
  - 每月雇佣 = min(V, ⌈U·f⌉)
- 兼容模式 (labor_full_employment = True): 雇佣所有失业者 (legacy Phase 0)
- 工资方程 (Taylor + 菲利普斯斜率): 通胀指数化 + κ·(NAIRU−u)
- 向下工资粘性: 紧缩期降薪幅度减半

SFC 注记:
- 解雇/雇佣本身不发生资金流, 只动 firm.employees 计数
- 工资支付由 core.step._pay_wages 处理
"""
from __future__ import annotations

import math

from financial_sim.core.state import SimulationState
from financial_sim.utils.logging import get_logger

logger = get_logger(__name__)


class LaborMarket:
    """Phase 1+ 劳动市场: 摩擦匹配 + 工资议价."""

    # ── 工资 (向下粘性) ──
    NAIRU = 0.05                          # 自然失业率 5%
    WAGE_PRESSURE_COEFF = 0.10            # κ: 失业缺口→工资(年率)

    # ── 摩擦 (可由 config 覆盖) ──
    DEFAULT_SEPARATION_RATE = 0.01        # 月度离职率 (≈12%/年)
    DEFAULT_MATCHING_EFFICIENCY = 0.5

    # ── 配置开关 ──
    full_employment: bool = False         # True=legacy "雇所有人"
    separation_rate: float = DEFAULT_SEPARATION_RATE
    matching_efficiency: float = DEFAULT_MATCHING_EFFICIENCY
    wage_adjust_freq: int = 6             # 工资调整频率(月)
    wage_phillips_coeff: float = WAGE_PRESSURE_COEFF

    def configure(
        self,
        full_employment: bool | None = None,
        separation_rate: float | None = None,
        matching_efficiency: float | None = None,
        wage_adjust_freq: int | None = None,
        wage_phillips_coeff: float | None = None,
    ) -> None:
        """运行时覆盖参数 (允许 config 与实例共存)."""
        if full_employment is not None:
            self.full_employment = full_employment
        if separation_rate is not None:
            self.separation_rate = separation_rate
        if matching_efficiency is not None:
            self.matching_efficiency = matching_efficiency
        if wage_adjust_freq is not None:
            self.wage_adjust_freq = wage_adjust_freq
        if wage_phillips_coeff is not None:
            self.wage_phillips_coeff = wage_phillips_coeff

    @classmethod
    def from_config(cls, config) -> LaborMarket:
        """从 SimConfig 构造并配置 (生产路径, 由 Simulation 调用)."""
        market = cls()
        market.configure(
            full_employment=getattr(config, "labor_full_employment", None),
            separation_rate=getattr(config, "labor_separation_rate", None),
            matching_efficiency=getattr(config, "labor_matching_efficiency", None),
            wage_adjust_freq=getattr(config, "labor_wage_adjust_freq", None),
            wage_phillips_coeff=getattr(config, "labor_wage_phillips_coeff", None),
        )
        return market

    # ════════════════════════════════════════════════════════════
    # 主入口
    # ════════════════════════════════════════════════════════════
    def clear(self, state: SimulationState) -> None:
        """月度劳动市场出清.

        顺序:
        1. 外生离职 (用 RNGManager 'labor_separation' 流抽样保证可复现)
        2. 雇佣 (legacy 全雇佣 或 摩擦匹配)
        3. 工资调整 (按 wage_adjust_freq 周期)
        4. 失业计时推进

        注: 不在内部从 state.config 自动 configure, 以保持测试隔离性.
        调用方应在构造仿真时一次性配置 (见 Simulation._build_state).
        """
        firm = state.firm
        if firm is None:
            return

        # 1. 外生离职
        self._apply_separations(state)

        # 2. 雇佣
        if self.full_employment:
            self._full_employment_hire(state)
        else:
            self._frictional_hire(state)

        # 3. 工资调整
        if state.t > 0 and state.t % self.wage_adjust_freq == 0:
            self._adjust_wages(state)
            for h in state.households:
                if h.employed:
                    h.wage = firm.wage_offered

        # 4. 失业计时推进
        for h in state.households:
            h.tick_unemployment()

    # ════════════════════════════════════════════════════════════
    # 1. 外生离职
    # ════════════════════════════════════════════════════════════
    def _apply_separations(self, state: SimulationState) -> None:
        """按 separation_rate 随机解雇员工. 使用 RNG 'labor' 流."""
        firm = state.firm
        if firm is None or firm.employees <= 0:
            return
        rate = self.separation_rate
        if rate <= 0:
            return

        mgr = getattr(state, "rng_manager", None)
        if mgr is not None:
            rng = mgr.stream("labor_separation")
            employed = [h for h in state.households if h.employed]
            if not employed:
                return
            n_separated = int(rng.binomial(len(employed), rate))
        else:
            # Fallback: 期望值, 不可复现
            n_separated = int(round(firm.employees * rate))

        n_separated = min(n_separated, firm.employees)
        if n_separated <= 0:
            return

        # 选择前 n_separated 个 employed (确定性切片; RNG 已控制 n)
        separated_idx = set()
        if mgr is not None:
            rng = mgr.stream("labor_separation")
            idx = rng.choice(len(employed), size=n_separated, replace=False)
            separated_idx = {int(i) for i in idx}
        for i, h in enumerate(employed):
            if i in separated_idx or (not separated_idx and n_separated > 0):
                h.lose_job()
                n_separated -= 1
                if n_separated <= 0:
                    break

        firm.fire(len(employed) - sum(1 for h in employed if h.employed))

    # ════════════════════════════════════════════════════════════
    # 2a. Legacy: 全雇佣
    # ════════════════════════════════════════════════════════════
    def _full_employment_hire(self, state: SimulationState) -> None:
        """雇佣所有失业者 (Phase 0 行为, 仅用于回归测试)."""
        firm = state.firm
        if firm is None:
            return
        for h in state.households:
            if not h.employed:
                firm.hire(1)
                h.find_job(sector=firm.sector, wage=firm.wage_offered)

    # ════════════════════════════════════════════════════════════
    # 2b. 摩擦雇佣 (默认)
    # ════════════════════════════════════════════════════════════
    def _frictional_hire(self, state: SimulationState) -> None:
        """搜索-匹配模型: f(θ) = 1 − exp(−η·V/U), 雇佣数取 ⌈U·f⌉ 与 V 的较小值."""
        firm = state.firm
        if firm is None:
            return

        # 目标就业 = 基准 (由 firm.baseline_employees 或劳动力规模估算)
        desired = firm.baseline_employees if firm.baseline_employees > 0 else len(state.households)
        # 平滑调整: desired 可随生产缺口微调 (Phase 1 简化为固定)
        vacancies = max(0, desired - firm.employees)
        unemployed_hh = [h for h in state.households if not h.employed]
        n_unemployed = len(unemployed_hh)
        if vacancies == 0 or n_unemployed == 0:
            return

        # 紧度 θ = V/U. 若 U > 0 且 V > 0:
        theta = vacancies / n_unemployed
        f = 1.0 - math.exp(-self.matching_efficiency * theta)
        n_hires = min(vacancies, int(math.ceil(n_unemployed * f)))

        # FIFO 雇佣 (确定性顺序, RNG 仅控制离职环节)
        for h in unemployed_hh[:n_hires]:
            firm.hire(1)
            h.find_job(sector=firm.sector, wage=firm.wage_offered)

        logger.debug(
            f"  labor: desired={desired}, V={vacancies}, U={n_unemployed}, "
            f"θ={theta:.2f}, f={f:.2f}, hires={n_hires}"
        )

    # ════════════════════════════════════════════════════════════
    # 3. 工资调整
    # ════════════════════════════════════════════════════════════
    def _adjust_wages(self, state: SimulationState) -> None:
        """基于通胀预期 + 失业缺口的工资方程 (向下粘性).

        Δw/w = π_exp / 2 + κ · (NAIRU − u)   (紧缩期 κ × 0.5)
        """
        firm = state.firm
        if firm is None:
            return

        unemployment = state.unemployment_rate_calc()
        unemployment_gap = self.NAIRU - unemployment  # >0 = 劳动力紧张

        exp_module = getattr(state, "inflation_expectation", None)
        indexation = (exp_module.value / 2.0) if exp_module is not None else 0.0

        if unemployment_gap >= 0:
            pressure = indexation + self.wage_phillips_coeff * unemployment_gap
        else:
            # 向下粘性: 失业>NAIRU 时降薪减半且无指数化上推
            pressure = 0.5 * (
                indexation + self.wage_phillips_coeff * unemployment_gap
            )

        firm.wage_offered *= 1.0 + pressure


__all__ = ["LaborMarket"]
