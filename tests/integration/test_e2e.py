"""End-to-end test: 跑 12 个月, 验证仿真能完成且 SFC 不违反."""
from __future__ import annotations

import pytest

from financial_sim.core import Simulation


@pytest.mark.integration
class TestEndToEndBaseline:
    """最基础的 e2e: 跑 12 个月, 不应崩溃."""

    def test_run_12_months_completes(self, small_config):
        """小规模 12 个月跑通."""
        sim = Simulation(small_config)
        sim.run(n_ticks=12)
        assert sim.state.t == 12

    def test_run_24_months_macro_stable(self, small_config):
        """24 个月, 宏观变量在合理范围."""
        sim = Simulation(small_config)
        sim.run(n_ticks=24)
        state = sim.state

        # 时间推进
        assert state.t == 24

        # GDP > 0
        assert state.real_gdp > 0

        # 失业率在合理范围 (0-100%)
        assert 0.0 <= state.unemployment_rate <= 1.0

        # 政策利率在合理范围
        cb = state.central_bank
        assert cb is not None
        assert -0.01 <= cb.policy_rate <= 0.30

    def test_macro_history_recorded(self, small_config):
        """宏观历史应被记录."""
        sim = Simulation(small_config)
        sim.run(n_ticks=12)
        # 12 tick 后, 应有 12 条历史 (每个 tick 结束记录一次)
        assert len(sim.state.macro_history) == 12

    def test_default_config_runs(self):
        """默认配置 (1000 HHs) 应能跑."""
        sim = Simulation()  # default config
        sim.run(n_ticks=12)
        assert sim.state.t == 12


@pytest.mark.integration
class TestSFCDuringSimulation:
    """SFC 校验应在每 tick 触发, 跑完应无违规."""

    def test_no_sfc_violations_in_12_months(self, small_config):
        sim = Simulation(small_config)
        sim.run(n_ticks=12)
        # 检查所有 tick 的 SFC violations
        total_violations = sum(len(v) for v in sim.state.sfc_violations)
        assert total_violations == 0, (
            f"SFC violations occurred: {sim.state.sfc_violations[:3]}"
        )

    def test_no_sfc_violations_24_months(self, small_config):
        sim = Simulation(small_config)
        sim.run(n_ticks=24)
        total = sum(len(v) for v in sim.state.sfc_violations)
        assert total == 0, f"SFC violations: {sim.state.sfc_violations}"
