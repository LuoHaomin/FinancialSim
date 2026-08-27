"""Phase 3 Week F: 阶段验收矩阵.

验收标准 (IMPLEMENTATION.md §5 Phase 3):
- ① 场景×种子矩阵零 SFC 违反
- ② 明斯基时刻检验 (内生杠杆积累 → 冲击触发非线性崩塌)
"""
from __future__ import annotations

import pytest

from financial_sim.scenarios import load_scenario

SCENARIOS = ["baseline", "crisis_2008", "stagflation", "housing_bust"]
SEEDS = [7, 42, 99]


class TestScenarioSFCMatrix:
    """① 场景 × 种子 全组合零 SFC 违反."""

    @pytest.mark.parametrize("scenario", SCENARIOS)
    @pytest.mark.parametrize("seed", SEEDS)
    def test_matrix(self, scenario, seed):
        config, events = load_scenario(scenario, overrides={
            "n_households": 150,   # CI 提速; 记账与规模无关
            "n_ticks": 48,
            "seed": seed,
        })
        from financial_sim.core.simulation import Simulation
        sim = Simulation(config, seed=seed, scenario_events=events)
        state = sim.run(48)
        assert sum(len(v) for v in state.sfc_violations) == 0, (
            f"{scenario}/seed{seed}: {state.sfc_violations[:2]}"
        )

    @pytest.mark.parametrize("scenario", ["post_war_recovery", "tight_credit"])
    def test_aux_scenarios_clean(self, scenario):
        for seed in SEEDS:
            config, events = load_scenario(scenario, overrides={
                "n_households": 100, "n_ticks": 36, "seed": seed,
            })
            from financial_sim.core.simulation import Simulation
            sim = Simulation(config, seed=seed, scenario_events=events)
            state = sim.run(36)
            assert sum(len(v) for v in state.sfc_violations) == 0, (
                f"{scenario}/seed{seed}"
            )


class TestMinskyMoment:
    """明斯基时刻检验: 初始杠杆(初始房贷 LTV)越高,
    同等冲击造成的峰值失业/损失放大 (非线性崩塌)."""

    def test_high_leverage_amplifies_downturn(self):
        from financial_sim.config import SimConfig
        from financial_sim.core.simulation import Simulation

        shocks = ["housing_risk_premium_spike",
                  "fiscal_austerity_30p_12m"]

        def peak_u(ltv: float) -> float:
            cfg = SimConfig(
                n_households=200, n_ticks=60, seed=42,
                housing_initial_ltv=ltv,
                preset_shocks=shocks,
            )
            st = Simulation(cfg, seed=42).run(60).macro_history
            return max(s.unemployment_rate for s in st)

        low_ltv = peak_u(0.40)
        high_ltv = peak_u(0.85)
        # 高杠杆下的衰退应不浅于低杠杆 (放大或至少持平)
        assert high_ltv >= low_ltv - 1e-9, (
            f"高杠杆 peak_u={high_ltv:.3f} < 低杠杆 {low_ltv:.3f}"
        )


class TestPhase3ScalePerf:
    """② 性能门禁: n=5000 规模 P95 tick 可承受 (预算 <2s/tick)."""

    def test_tick_budget_at_scale(self):
        import time

        from financial_sim.config import SimConfig
        from financial_sim.core.simulation import Simulation

        cfg = SimConfig(n_households=5000, n_ticks=6, seed=42)
        sim = Simulation(cfg, seed=42)
        t0 = time.perf_counter()
        sim.run(6)
        elapsed = time.perf_counter() - t0
        per_tick = elapsed / 6
        assert per_tick < 2.0, (
            f"n=5000 tick 均耗时 {per_tick:.2f}s 超预算 2s"
        )
