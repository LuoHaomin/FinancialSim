"""Phase 3 Week B 单元测试: 动态劳动需求 + 失业疤痕效应."""
from __future__ import annotations

import pytest

from financial_sim.agents.firm import Firm
from financial_sim.config import SimConfig
from financial_sim.markets.labor import LaborMarket


def _make_labor(**kwargs) -> LaborMarket:
    return LaborMarket.from_config(SimConfig(**kwargs))


class TestDynamicLaborDemand:
    """销售/需求驱动的目标就业更新."""

    def _setup_firms(self):
        firms = [
            Firm(id=f"f{i}", sector="consumer_goods", employees=100)
            for i in range(3)
        ]
        for f in firms:
            f.baseline_employees = f.employees
            f.price = 1.0
            f.productivity = 1.0
        return firms

    def test_no_signal_keeps_employment(self):
        lm = _make_labor()
        firms = self._setup_firms()
        state = SimulationStateStub(firms)
        state.households = []
        lm._update_labor_demand(state)
        assert firms[0].employees == 100
        # 无销售信号时维持现状 — 目标不超过当前员工数太多
        assert firms[0].baseline_employees <= 125  # up_speed cap

    def test_low_demand_cuts_target(self):
        lm = _make_labor(labor_adjust_down_speed=0.35)
        firms = self._setup_firms()
        firms[0].sales_history = [10.0]
        state = SimulationStateStub(firms)
        state.households = [
            HouseholdStub(firms[0].id) for _ in range(100)
        ]
        # 每个员工对应 household
        for h in state.households:
            h.employed = True
        n_before = sum(f.employees for f in firms)
        lm._update_labor_demand(state)
        fired = n_before - sum(f.employees for f in firms)
        # 原始目标 ≈ 12, 但每月裁员受 adjust_down_speed=0.35 封顶
        # → baseline 只能降到 100×(1−0.35)=65
        assert firms[0].baseline_employees == 65
        assert fired == 35

    def test_high_demand_grows_gradually(self):
        lm = _make_labor(labor_adjust_up_speed=0.25)
        firms = self._setup_firms()
        firms[0].sales_history = [500.0]
        state = SimulationStateStub(firms)
        state.households = []
        lm._update_labor_demand(state)
        # 上调受 25%/月 封顶
        assert firms[0].baseline_employees == 125

    def test_negative_history_index_guarded(self):
        lm = _make_labor(labor_demand_response_delay=5)
        firms = self._setup_firms()
        firms[0].sales_history = [50.0, 60.0]
        state = SimulationStateStub(firms)
        state.households = []
        lm._update_labor_demand(state)
        # 索引越界取最早一期 (50×1.2=60), 再被下调封顶 clamp 到 65
        assert firms[0].baseline_employees == 65


class TestScarEffect:
    """长期失业疤痕: 再就业工资折扣."""

    def test_within_grace_no_discount(self):
        lm = _make_labor()
        h = HouseholdLike(unemployment_duration=6)
        assert lm._scar_discounted_wage(100.0, h) == pytest.approx(100.0)

    def test_long_unemployment_discounted(self):
        lm = _make_labor(
            wage_scar_discount_rate=0.01,
            wage_scar_grace_months=6,
            wage_scar_discount_cap=0.30,
        )
        h = HouseholdLike(unemployment_duration=16)  # 超 10 月
        expected = 100.0 * (1 - 0.01 * 10)
        assert lm._scar_discounted_wage(100.0, h) == pytest.approx(expected)

    def test_discount_capped(self):
        lm = _make_labor()
        h = HouseholdLike(unemployment_duration=1000)
        wage = lm._scar_discounted_wage(100.0, h)
        assert wage == pytest.approx(70.0)


# ════════════════════════════════════════════════════════════
# 轻量 stub (避免依赖完整 SimulationState / Household 构造)
# ════════════════════════════════════════════════════════════
class SimulationStateStub:
    def __init__(self, firms):
        self.firms = firms
        self.households = []


class HouseholdStub:
    def __init__(self, employer_id=None):
        self.employed = False
        self.employer_id = employer_id
        self.unemployment_duration = 0

    def lose_job(self):
        self.employed = False
        self.unemployment_duration = 0


class HouseholdLike:
    def __init__(self, unemployment_duration=0):
        self.unemployment_duration = unemployment_duration
