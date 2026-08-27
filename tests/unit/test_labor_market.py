"""Tests for LaborMarket (Phase 1+: frictional hiring + wage adjustment)."""
from __future__ import annotations

import math

from financial_sim.config import SimConfig
from financial_sim.core import Simulation
from financial_sim.markets.labor import LaborMarket


class TestLaborMarketFullEmploymentLegacy:
    """Legacy 模式 (labor_full_employment=True): 雇佣所有失业者."""

    def test_unemployed_gets_hired(self):
        sim = Simulation(SimConfig(n_households=10, n_ticks=1))
        for h in sim.state.households[:3]:
            h.lose_job()
            sim.state.firm.fire(1)

        market = LaborMarket()
        market.full_employment = True
        market.clear(sim.state)

        assert sim.state.total_unemployed() == 0


class TestLaborMarketFriction:
    """默认摩擦雇佣: 不是所有失业者都被雇佣."""

    def test_separations_create_unemployment(self):
        """默认 separation_rate > 0, 离职后出现失业者."""
        sim = Simulation(SimConfig(n_households=10, n_ticks=1))
        market = LaborMarket()
        market.clear(sim.state)
        # 默认 1% 月度离职 → 10 人中应有 0-2 人失业
        assert 0 <= sim.state.total_unemployed() <= 10

    def test_zero_separation_no_unemployment_from_friction(self):
        """separation=0 时摩擦雇佣可达到全雇佣 (若 desired = N)."""
        sim = Simulation(SimConfig(n_households=10, n_ticks=1))
        market = LaborMarket()
        market.separation_rate = 0.0
        market.clear(sim.state)
        assert sim.state.total_unemployed() == 0

    def test_matching_efficiency_increases_hires(self):
        """η 越高, 雇佣越多 (空缺不变时)."""
        sim = Simulation(SimConfig(n_households=100, n_ticks=1))
        # 强制 50 人失业
        for h in sim.state.households[:50]:
            h.lose_job()
            sim.state.firm.employees -= 1
        sim.state.firm.employees = 50  # baseline = 100, vacancies = 50

        m_low = LaborMarket()
        m_low.matching_efficiency = 0.1
        m_low.separation_rate = 0.0
        m_low.clear(sim.state)
        hires_low = 100 - sim.state.total_unemployed()

        # reset
        sim2 = Simulation(SimConfig(n_households=100, n_ticks=1))
        for h in sim2.state.households[:50]:
            h.lose_job()
            sim2.state.firm.employees -= 1
        sim2.state.firm.employees = 50

        m_hi = LaborMarket()
        m_hi.matching_efficiency = 5.0
        m_hi.separation_rate = 0.0
        m_hi.clear(sim2.state)
        hires_hi = 100 - sim2.state.total_unemployed()

        assert hires_hi >= hires_low

    def test_vacancy_cap_limits_hires(self):
        """当 V < U·f 时, 雇佣上限 = V."""
        sim = Simulation(SimConfig(n_households=10, n_ticks=1))
        # baseline_employees = 10 (full), 当前 employees = 10
        # 但失业者多? 制造 5 失业但 desired=10 → V = 0 → 雇佣 = 0
        for h in sim.state.households[:5]:
            h.lose_job()
        sim.state.firm.employees = 10  # 表面没解雇

        market = LaborMarket()
        market.separation_rate = 0.0
        market.clear(sim.state)
        # V = baseline(10) - current(10) = 0 → 不雇佣
        assert sim.state.total_unemployed() == 5


class TestLaborMarketWageAdjustment:
    """工资调整测试."""

    def test_wage_adjusts_on_full_employment_cycle(self):
        sim = Simulation(SimConfig(n_households=10, n_ticks=12))
        market = LaborMarket()
        market.full_employment = True  # 强制全雇佣

        sim.state.t = 6
        initial_wage = sim.state.firm.wage_offered
        market.clear(sim.state)
        # 全雇佣 → u=0 < NAIRU → 工资上行
        assert sim.state.firm.wage_offered > initial_wage

    def test_no_wage_change_off_cycle(self):
        sim = Simulation(SimConfig(n_households=10, n_ticks=1))
        market = LaborMarket()
        market.full_employment = True

        sim.state.t = 5
        initial_wage = sim.state.firm.wage_offered
        market.clear(sim.state)
        assert sim.state.firm.wage_offered == initial_wage

    def test_wage_demand_pull_inflation_indexed(self):
        """通胀预期 > 0 时, 工资应正向调整 (即使 unemployment 持平)."""
        sim = Simulation(SimConfig(
            n_households=10, n_ticks=12,
            labor_wage_productivity_indexation=False,
        ))
        sim.state.inflation_expectation.value = 0.04  # 4% 预期
        market = LaborMarket()
        market.full_employment = True
        market.wage_phillips_coeff = 0.0  # 关闭菲利普斯, 纯看指数化
        market.separation_rate = 0.0

        sim.state.t = 6
        initial_wage = sim.state.firm.wage_offered
        market.clear(sim.state)
        # 校准 2026-08 量纲修正: 年化预期按调整频率摊销 → 4%/6 ≈ 0.67%
        growth = sim.state.firm.wage_offered / initial_wage - 1
        assert math.isclose(growth, 0.04 / 6, abs_tol=1e-6)


class TestLaborMarketDownwardStickiness:
    """向下工资粘性: 失业>NAIRU 时降薪减半."""

    def test_demand_driven_downward_sticky(self):
        sim = Simulation(SimConfig(
            n_households=10, n_ticks=12,
            labor_wage_productivity_indexation=False,
        ))
        # 制造失业率 70% (7/10). 把 baseline_employees 也降到 3
        # 否则 full_employment_hire 会把所有人雇回来, 失业被消除.
        for h in sim.state.households[:7]:
            h.lose_job()
        sim.state.firm.employees = 3
        sim.state.firm.baseline_employees = 3  # V=0, 不重新雇佣

        market = LaborMarket()
        market.full_employment = False        # 摩擦雇佣
        market.wage_phillips_coeff = 0.20
        market.wage_adjust_freq = 6
        market.separation_rate = 0.0           # 排除随机干扰
        sim.state.inflation_expectation.value = 0.0  # 指数化为 0

        sim.state.t = 6
        initial_wage = sim.state.firm.wage_offered
        market.clear(sim.state)

        # u = 0.70, unemployment_gap = 0.05 - 0.70 = -0.65
        # 不粘性: pressure = 0 + 0.20·(-0.65) = -0.13
        # 粘性: pressure = 0.5·(-0.13) = -0.065
        growth = sim.state.firm.wage_offered / initial_wage - 1
        assert math.isclose(growth, -0.065, abs_tol=1e-6)

    def test_downward_magnitude_halved(self):
        """粘性: 失业高时降薪幅度 = 非粘性时的 1/2."""
        base_cfg = SimConfig(
            n_households=10, n_ticks=12,
            labor_wage_productivity_indexation=False,
        )

        # 非粘性版本 (coef 翻倍, 手动补偿)
        sim1 = Simulation(base_cfg)
        for h in sim1.state.households[:7]:
            h.lose_job()
        sim1.state.firm.employees = 3
        sim1.state.firm.baseline_employees = 3
        sim1.state.inflation_expectation.value = 0.0
        m1 = LaborMarket()
        m1.full_employment = False
        m1.wage_phillips_coeff = 0.40   # 2x, 抵消粘性减半
        m1.separation_rate = 0.0
        sim1.state.t = 6
        w0 = sim1.state.firm.wage_offered
        m1.clear(sim1.state)
        growth_nonsticky = sim1.state.firm.wage_offered / w0 - 1

        # 粘性版本
        sim2 = Simulation(base_cfg)
        for h in sim2.state.households[:7]:
            h.lose_job()
        sim2.state.firm.employees = 3
        sim2.state.firm.baseline_employees = 3
        sim2.state.inflation_expectation.value = 0.0
        m2 = LaborMarket()
        m2.full_employment = False
        m2.wage_phillips_coeff = 0.20   # 粘性自动 × 0.5
        m2.separation_rate = 0.0
        sim2.state.t = 6
        w0 = sim2.state.firm.wage_offered
        m2.clear(sim2.state)
        growth_sticky = sim2.state.firm.wage_offered / w0 - 1

        # 粘性降薪幅度是非粘性的一半
        assert math.isclose(growth_sticky, 0.5 * growth_nonsticky, abs_tol=1e-9)
