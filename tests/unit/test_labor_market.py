"""Tests for LaborMarket (Phase 0 simplified)."""
from __future__ import annotations

from financial_sim.config import SimConfig
from financial_sim.core import Simulation
from financial_sim.markets.labor import LaborMarket


class TestLaborMarketFullEmployment:
    def test_unemployed_gets_hired(self):
        """失业者应被雇佣."""
        sim = Simulation(SimConfig(n_households=10, n_ticks=1))
        # 让 3 个家庭失业
        for h in sim.state.households[:3]:
            h.lose_job()
            sim.state.firm.fire(1)

        assert sim.state.total_unemployed() == 3

        market = LaborMarket()
        market.clear(sim.state)

        assert sim.state.total_unemployed() == 0
        assert sim.state.total_employed() == 10


class TestLaborMarketWageAdjustment:
    def test_wage_adjusts_every_n_months(self):
        """每 6 个月调一次工资."""
        sim = Simulation(SimConfig(n_households=10, n_ticks=12))
        market = LaborMarket()

        # Tick 6 应触发调薪
        sim.state.t = 6
        initial_wage = sim.state.firm.wage_offered

        # 假设失业率 < NAIRU (full employment)
        unemployment = sim.state.unemployment_rate_calc()
        assert unemployment == 0  # 全雇佣 → 工资应涨

        market.clear(sim.state)

        # 工资应上涨
        assert sim.state.firm.wage_offered > initial_wage

    def test_no_wage_change_off_cycle(self):
        """非调薪月不调整."""
        sim = Simulation(SimConfig(n_households=10, n_ticks=1))
        market = LaborMarket()

        sim.state.t = 5  # 不在 6 的倍数上
        initial_wage = sim.state.firm.wage_offered

        market.clear(sim.state)

        assert sim.state.firm.wage_offered == initial_wage
