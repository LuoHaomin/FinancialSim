"""Performance tests for Phase 0 acceptance.

Phase 0 验收: 月主 tick P95 < 500ms (1000 家庭)
"""
from __future__ import annotations

import time

import numpy as np
import pytest

from financial_sim.config import SimConfig
from financial_sim.core import Simulation


@pytest.mark.integration
class TestPerformanceBudget:
    """性能预算."""

    def test_p95_tick_time_under_500ms(self):
        """1000 家庭, P95 tick time < 500ms."""
        config = SimConfig(n_households=1000, n_ticks=12)
        sim = Simulation(config)

        # 预热 (第一个 tick 较慢, 因初始化)
        sim.step()

        times = []
        for _ in range(11):  # 12 - 1 (预热) = 11 个计时 tick
            start = time.perf_counter()
            sim.step()
            times.append(time.perf_counter() - start)

        p95_ms = np.percentile(times, 95) * 1000
        mean_ms = np.mean(times) * 1000
        print(
            f"\n  Performance (1000 HHs, 11 ticks): "
            f"mean={mean_ms:.1f}ms, P95={p95_ms:.1f}ms, max={max(times)*1000:.1f}ms"
        )

        assert p95_ms < 500, f"P95 tick time {p95_ms:.0f}ms exceeds budget 500ms"

    def test_small_sim_runs_fast(self):
        """10 家庭, 1 tick 应 < 100ms."""
        config = SimConfig(n_households=10, n_ticks=1)
        sim = Simulation(config)

        start = time.perf_counter()
        sim.step()
        elapsed_ms = (time.perf_counter() - start) * 1000

        print(f"\n  Performance (10 HHs, 1 tick): {elapsed_ms:.1f}ms")
        assert elapsed_ms < 100, f"Small sim {elapsed_ms:.0f}ms exceeds 100ms"


@pytest.mark.integration
class TestMacroStability:
    """宏观变量在长时间仿真中应稳定 (Phase 0 简化经济).

    Phase 0 没有真实的金融反馈环, 因此"稳定"=宏观变量不发散.
    """

    def test_gdp_positive_24_months(self):
        """24 个月 GDP 应为正."""
        config = SimConfig(n_households=100, n_ticks=24)
        sim = Simulation(config)
        sim.run(n_ticks=24)
        assert sim.state.real_gdp > 0

    def test_unemployment_bounded(self):
        """失业率应在 [0, 1] 范围内."""
        config = SimConfig(n_households=100, n_ticks=24)
        sim = Simulation(config)
        sim.run(n_ticks=24)
        for snap in sim.state.macro_history:
            assert 0 <= snap.unemployment_rate <= 1

    def test_policy_rate_bounded(self):
        """政策利率应在合理范围 [-1%, 30%]."""
        config = SimConfig(n_households=100, n_ticks=24)
        sim = Simulation(config)
        sim.run(n_ticks=24)
        for snap in sim.state.macro_history:
            assert -0.01 <= snap.policy_rate <= 0.30

    def test_household_deposits_positive(self):
        """家庭存款应为非负."""
        config = SimConfig(n_households=100, n_ticks=24)
        sim = Simulation(config)
        sim.run(n_ticks=24)
        for h in sim.state.households:
            assert h.deposits >= 0, f"HH {h.id} has negative deposits: {h.deposits}"

    def test_bank_reserves_positive(self):
        """银行准备金不应为负."""
        config = SimConfig(n_households=100, n_ticks=24)
        sim = Simulation(config)
        sim.run(n_ticks=24)
        assert sim.state.bank.reserves >= 0

    def test_consumption_proportional_to_income(self):
        """总消费应近似 = 0.7 × 总收入 (MPC)."""
        config = SimConfig(n_households=100, n_ticks=12)
        sim = Simulation(config)
        sim.run(n_ticks=12)

        # Tick 6 应达到稳态
        snap = sim.state.macro_history[6]
        # 用当前 wage_offered 计算总理论收入 (HH.wage 在雇佣时固定)
        current_wage = sim.state.firm.wage_offered
        theoretical_income = current_wage * 100  # 100 HHs
        ratio = snap.total_consumption / theoretical_income
        # Phase 0 简化经济, 允许较大偏差
        assert 0.5 < ratio < 1.5, f"Consumption/income ratio: {ratio:.2f}"
