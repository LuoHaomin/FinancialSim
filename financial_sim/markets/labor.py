"""劳动市场: 工资粘性 + 失业 (Phase 0 简化)."""
from __future__ import annotations

from financial_sim.core.state import SimulationState


class LaborMarket:
    """Phase 0: 简化劳动市场.

    机制:
    - 全雇佣 / 全失业 (无部分时间)
    - 工资粘性: 每 6 个月调整一次
    - 失业反馈: 失业率 > NAIRU → 工资降; < NAIRU → 工资升

    Phase 1 加入:
    - 完整工资议价方程 (Taylor 1979 + 菲利普斯曲线)
    - 失业摩擦 (job_search_intensity × 保留工资)
    - 疤痕效应 (long-term unemployment 降低人力资本)
    """

    WAGE_ADJUSTMENT_FREQ = 6  # 每 6 个月调一次
    NAIRU = 0.05             # 自然失业率 5%
    WAGE_PRESSURE_COEFF = 0.5  # 工资对失业缺口的反应

    def clear(self, state: SimulationState) -> None:
        """Phase 0: 雇佣所有失业者, 定期调整工资."""
        firm = state.firm
        if firm is None:
            return

        # 1. 雇佣所有失业者 (full employment)
        unemployed = [h for h in state.households if not h.employed]
        for h in unemployed:
            firm.hire(1)
            h.find_job(sector=firm.sector, wage=firm.wage_offered)

        # 2. 工资调整 (每 N 个月)
        if state.t > 0 and state.t % self.WAGE_ADJUSTMENT_FREQ == 0:
            self._adjust_wages(state)

    def _adjust_wages(self, state: SimulationState) -> None:
        """基于失业率调整工资."""
        firm = state.firm
        if firm is None:
            return

        unemployment = state.unemployment_rate_calc()

        # 失业反馈: 失业 > NAIRU → 工资降; < NAIRU → 工资升
        unemployment_gap = (self.NAIRU - unemployment) / self.NAIRU
        # 上行敏感, 下行粘性 (Phase 1 完整版)
        if unemployment_gap > 0:
            pressure = self.WAGE_PRESSURE_COEFF * unemployment_gap
        else:
            pressure = 0.2 * unemployment_gap  # 下行更粘

        firm.wage_offered *= 1 + pressure
