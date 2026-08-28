"""Phase 2 危机涌现集成测试 (2008 型场景).

场景: 房价风险溢价飙升 ×2 (yield +8pp) + 财政紧缩 + 货币紧缩
验收: 冲击传导为 房价下跌 → 抵押违约/NPL → 银行失败 → 政府救助,
全程零 SFC 违反.
"""
from __future__ import annotations

import pytest

from financial_sim.config import SimConfig
from financial_sim.core.simulation import Simulation

CRISIS_SHOCKS = [
    "housing_risk_premium_spike",
    "housing_risk_premium_spike",
    "fiscal_austerity_30p_12m",
    "tightening_50bp_6m",
]


def _run_crisis(n_ticks: int = 48, n_households: int = 200) -> Simulation:
    cfg = SimConfig(
        n_households=n_households,
        n_banks=1,
        n_ticks=n_ticks,
        wealth_effect_coef=0.05,
        preset_shocks=CRISIS_SHOCKS,
    )
    sim = Simulation(cfg, seed=7)
    sim.run(n_ticks)
    return sim


@pytest.mark.integration
class TestCrisisEmergence:
    def test_sfc_holds_throughout(self):
        sim = _run_crisis()
        assert sum(len(v) for v in sim.state.sfc_violations) == 0

    def test_housing_price_collapses(self):
        """风险溢价飙升后房价应显著低于初始水平."""
        sim = _run_crisis()
        assert sim.state.housing_price < 120.0 * 0.5

    def test_bank_failures_occur_and_are_recorded(self):
        """Phase 3.5 行为化违约级联 → 银行失败被记录."""
        sim = _run_crisis(60)
        assert len(sim.state.failed_banks) >= 1

    def test_mortgage_defaults_generated(self):
        """Phase 3.5 行为化违约触发: 连续 N 月负资产 → 抵押违约级联."""
        sim = _run_crisis()
        primary = sim.state.banks[0]
        assert primary.npl_writes_off_cumulative > 0

    def test_post_failure_capital_not_runaway_negative(self):
        """失败银行经政府救助后不应出现资本无界发散."""
        sim = _run_crisis(60)
        for b in sim.state.banks:
            assert b.capital > -1e-6

    def test_government_acted_as_backstop(self):
        """银行失败的代价应体现在政府资产负债表上 (other_assets / debt)."""
        sim = _run_crisis(60)
        if not sim.state.failed_banks:
            pytest.skip("no bank failed in this draw")
        gov = sim.state.government
        assert gov.other_assets > 0 or gov.debt > 120.0


@pytest.mark.integration
class TestBaselineMultiBankStillClean:
    def test_multibank_baseline_no_violation(self):
        cfg = SimConfig(n_households=100, n_banks=3, n_ticks=24)
        st = Simulation(cfg, seed=11).run(24)
        assert sum(len(v) for v in st.sfc_violations) == 0

    def test_housing_price_stays_near_fundamental(self):
        cfg = SimConfig(n_households=100, n_banks=1, n_ticks=36)
        st = Simulation(cfg, seed=11).run(36)
        # 基本面价 = rent×12/yield = 120; 允许 ±35% 波动带
        assert 78.0 <= st.housing_price <= 162.0
