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
    # 年化工资菲利普斯曲线斜率: 失业缺口每 1pt → 工资增长差 0.1pt/年
    WAGE_PRESSURE_COEFF = 0.10

    def clear(self, state: SimulationState) -> None:
        """Phase 1: 雇佣所有失业者, 定期调整工资.

        工资增长 = 通胀预期(年化)/2 + κ × 失业缺口
        下行对称性弱化: 失业超过 NAIRU 时下调幅度减半 (向下粘性).
        """
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
            # 在职员工工资跟随新 offer 水平 (保证聚合口径一致)
            for h in state.households:
                if h.employed:
                    h.wage = firm.wage_offered

    def _adjust_wages(self, state: SimulationState) -> None:
        """基于通胀预期 + 失业缺口的工资方程 (年率折半为半年频率)."""
        firm = state.firm
        if firm is None:
            return

        unemployment = state.unemployment_rate_calc()
        unemployment_gap = self.NAIRU - unemployment  # >0 = 劳动力市场紧张

        exp_module = getattr(state, "inflation_expectation", None)
        indexation = (
            exp_module.value / 2.0 if exp_module is not None else 0.0
        )
        if unemployment_gap >= 0:
            pressure = indexation + self.WAGE_PRESSURE_COEFF * unemployment_gap
        else:
            # 向下粘性: 紧缩时期降薪幅度减半且无指数化上推
            pressure = 0.5 * (indexation + self.WAGE_PRESSURE_COEFF * unemployment_gap)

        firm.wage_offered *= 1.0 + pressure
