"""Tests for scenario YAML loader (P0-c)."""
from __future__ import annotations

import pytest

from financial_sim.config import SimConfig
from financial_sim.scenarios import list_scenarios, load_scenario


class TestScenarioLoader:
    def test_list_scenarios_finds_known_files(self):
        names = list_scenarios()
        assert "baseline" in names
        assert "crisis_2008" in names

    def test_load_baseline_returns_valid_config(self):
        cfg, em = load_scenario("baseline")
        assert isinstance(cfg, SimConfig)
        assert cfg.n_ticks == 1200
        assert cfg.preset_shocks == []
        assert em is None

    def test_load_crisis_has_preset_shocks(self):
        cfg, em = load_scenario("crisis_2008")
        assert cfg.preset_shocks != []
        assert em is not None
        # Crisis 应该有 4 个事件
        assert len(em.events) == 4

    def test_unknown_scenario_raises(self):
        with pytest.raises(FileNotFoundError):
            load_scenario("does_not_exist")

    def test_overrides_apply(self):
        cfg, _ = load_scenario(
            "baseline", overrides={"n_ticks": 12, "n_households": 50}
        )
        assert cfg.n_ticks == 12
        assert cfg.n_households == 50

    def test_yaml_seed_is_used_by_default(self):
        cfg, _ = load_scenario("crisis_2008")
        assert cfg.seed == 7

    def test_yaml_does_not_leak_extra_keys(self):
        """YAML 顶层额外字段 (描述等) 不应污染 SimConfig."""
        cfg, _ = load_scenario("crisis_2008")
        # description 字段被 pop 掉了, 不应触发 ValidationError
        assert hasattr(cfg, "n_households")


class TestScenarioIntegration:
    """End-to-end: 加载 scenario, 跑 12 月, 验证不出 SFC 违反."""

    def test_baseline_runs_clean(self):
        cfg, em = load_scenario("baseline", overrides={"n_ticks": 12})
        from financial_sim.core.simulation import Simulation
        sim = Simulation(cfg, seed=cfg.seed, scenario_events=em)
        sim.run(12)
        assert sum(len(v) for v in sim.state.sfc_violations) == 0
