"""Tests for ShockEvent event system (Phase 1+)."""
from __future__ import annotations

import pytest

from financial_sim.config import SimConfig
from financial_sim.core import Simulation
from financial_sim.simulation.events import (
    PRESET_SHOCKS,
    EventManager,
    ShockEvent,
    build_event_manager,
    make_preset_shock,
)


# ════════════════════════════════════════════════════════════
# ShockEvent 数据类
# ════════════════════════════════════════════════════════════
class TestShockEvent:
    def test_one_shot_active_only_at_trigger(self):
        ev = ShockEvent(
            name="x", trigger_t=10, channel="policy_rate",
            magnitude=0.01, duration=0, one_shot=True,
        )
        assert ev.is_active_at(10)
        assert not ev.is_active_at(9)
        assert not ev.is_active_at(11)

    def test_duration_active_in_window(self):
        ev = ShockEvent(
            name="x", trigger_t=10, channel="policy_rate",
            magnitude=0.01, duration=6, one_shot=False,
        )
        assert ev.is_active_at(10)
        assert ev.is_active_at(15)  # trigger_t + 5
        assert not ev.is_active_at(16)  # trigger_t + duration = 16 (excluded)
        assert not ev.is_active_at(9)

    def test_zero_duration_one_shot(self):
        ev = ShockEvent(
            name="x", trigger_t=5, channel="x", magnitude=0, duration=0,
        )
        assert ev.duration == 0
        # 默认 one_shot=True
        assert ev.is_active_at(5)
        assert not ev.is_active_at(6)


# ════════════════════════════════════════════════════════════
# PRESET_SHOCKS 库
# ════════════════════════════════════════════════════════════
class TestPresetShocks:
    def test_all_presets_have_required_fields(self):
        for name, cfg in PRESET_SHOCKS.items():
            assert "channel" in cfg, f"{name} missing channel"
            assert "magnitude" in cfg, f"{name} missing magnitude"
            assert "duration" in cfg, f"{name} missing duration"
            assert "one_shot" in cfg, f"{name} missing one_shot"

    def test_make_preset_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown preset"):
            make_preset_shock("nonexistent_shock", trigger_t=0)

    def test_make_preset_uses_trigger_t(self):
        ev = make_preset_shock("rate_hike_100bp", trigger_t=24)
        assert ev.trigger_t == 24
        assert ev.channel == "policy_rate"
        assert ev.magnitude == pytest.approx(0.01)


# ════════════════════════════════════════════════════════════
# EventManager
# ════════════════════════════════════════════════════════════
class TestEventManager:
    def test_empty_manager_no_active(self):
        mgr = EventManager()
        assert mgr.active_at(0) == []
        assert mgr.active_at(100) == []

    def test_add_and_active(self):
        mgr = EventManager()
        ev = make_preset_shock("rate_hike_100bp", trigger_t=12)
        mgr.add(ev)
        assert mgr.active_at(12) == [ev]
        assert mgr.active_at(11) == []

    def test_build_event_manager_from_list(self):
        mgr = build_event_manager(
            ["rate_hike_100bp", "fiscal_austerity_30p_12m"],
            trigger_offsets=[6, 24],
        )
        assert len(mgr.events) == 2
        fired = mgr.active_at(6)
        assert len(fired) == 1
        assert fired[0].name == "rate_hike_100bp"
        fired = mgr.active_at(30)  # 24 + 6 = 30 still active
        assert len(fired) == 1
        assert fired[0].name == "fiscal_austerity_30p_12m"


# ════════════════════════════════════════════════════════════
# Effects 聚合
# ════════════════════════════════════════════════════════════
class TestComputeEffects:
    def test_policy_rate_accumulates(self):
        mgr = EventManager()
        mgr.extend([
            ShockEvent("a", 0, "policy_rate", 0.01, one_shot=True),
            ShockEvent("b", 0, "policy_rate", -0.005, one_shot=True),
        ])
        effects = mgr.compute_effects(mgr.active_at(0))
        assert effects["policy_rate_delta"] == pytest.approx(0.005)

    def test_gov_spending_replaces(self):
        mgr = EventManager()
        mgr.extend([
            ShockEvent("a", 0, "gov_spending", 0.7, one_shot=True),
            ShockEvent("b", 0, "gov_spending", 1.2, one_shot=True),
        ])
        effects = mgr.compute_effects(mgr.active_at(0))
        # 替换语义: 取最后一个
        assert effects["gov_spending_mult"] == pytest.approx(1.2)

    def test_energy_price_one_event_replaces(self):
        mgr = EventManager()
        mgr.extend([
            ShockEvent("a", 0, "energy_price", 0.3, one_shot=True),
        ])
        effects = mgr.compute_effects(mgr.active_at(0))
        # productivity mult = 1/(1+0.3) ≈ 0.769
        assert effects["energy_price_mult"] == pytest.approx(1.0 / 1.3)


# ════════════════════════════════════════════════════════════
# Integration with state
# ════════════════════════════════════════════════════════════
class TestEventApplicationToState:
    def test_policy_rate_shock_increases_cb_rate(self):
        sim = Simulation(SimConfig(n_households=10, n_ticks=1))
        initial_rate = sim.state.central_bank.policy_rate
        mgr = EventManager()
        mgr.add(make_preset_shock("rate_hike_100bp", trigger_t=0))
        mgr.apply_to_state(sim.state, t=0)
        # +100bp 但还要被 taylor_rule 在 _cb_decisions 覆盖 → 我们手动验证 shock 直接修改
        assert sim.state.central_bank.policy_rate == pytest.approx(
            initial_rate + 0.01
        )

    def test_gov_spending_shock_sets_multiplier(self):
        sim = Simulation(SimConfig(n_households=10, n_ticks=1))
        mgr = EventManager()
        mgr.add(make_preset_shock("fiscal_austerity_30p_12m", trigger_t=0))
        mgr.apply_to_state(sim.state, t=0)
        assert mgr.get_gov_spending_multiplier(sim.state) == pytest.approx(0.70)

    def test_gov_spending_resets_when_no_event(self):
        sim = Simulation(SimConfig(n_households=10, n_ticks=1))
        mgr = EventManager()
        mgr.add(make_preset_shock("fiscal_austerity_30p_12m", trigger_t=5))
        # t=0: 没有事件 → 重置 multiplier = 1.0
        mgr.apply_to_state(sim.state, t=0)
        assert mgr.get_gov_spending_multiplier(sim.state) == 1.0

    def test_tax_rate_override(self):
        sim = Simulation(SimConfig(n_households=10, n_ticks=1))
        mgr = EventManager()
        mgr.add(make_preset_shock("tax_hike_5pp_24m", trigger_t=0))
        mgr.apply_to_state(sim.state, t=0)
        # base income_tax_rate = 0.25; override 应为 0.25 + 0.05 = 0.30
        assert mgr.get_income_tax_rate(sim.state, default=0.25) == pytest.approx(0.30)

    def test_wage_shock_increases_wage(self):
        sim = Simulation(SimConfig(n_households=10, n_ticks=1))
        initial = sim.state.firm.wage_offered
        mgr = EventManager()
        mgr.add(make_preset_shock("wage_shock_plus10p", trigger_t=0))
        mgr.apply_to_state(sim.state, t=0)
        # +10% 一次性
        assert sim.state.firm.wage_offered == pytest.approx(initial * 1.10)


# ════════════════════════════════════════════════════════════
# End-to-end through monthly_tick
# ════════════════════════════════════════════════════════════
class TestEventManagerE2E:
    def test_event_fires_at_configured_tick(self):
        config = SimConfig(
            n_households=10, n_ticks=6,
            preset_shocks=["rate_hike_100bp"],
        )
        sim = Simulation(config)
        # 仿真会自动构造 EventManager, trigger_t 默认为 12
        # 因为只跑 6 ticks, 事件不会触发
        sim.run(n_ticks=6)
        assert all(
            s["name"] != "rate_hike_100bp" for s in sim.state.shock_log
        )

    def test_event_fires_at_early_tick(self):
        config = SimConfig(
            n_households=10, n_ticks=6,
            preset_shocks=["rate_hike_100bp"],
        )
        sim = Simulation(config)
        # 手动注入早期触发的事件
        from financial_sim.simulation.events import make_preset_shock
        sim.state.event_manager.add(
            make_preset_shock("rate_hike_100bp", trigger_t=3)
        )
        sim.run(n_ticks=6)
        assert any(s["name"] == "rate_hike_100bp" for s in sim.state.shock_log)
        assert any(s["t"] == 3 for s in sim.state.shock_log)
