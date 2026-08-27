"""StateSnapshot: 保存/恢复往返一致性."""
from __future__ import annotations

import pytest

from financial_sim.config import SimConfig
from financial_sim.core.simulation import Simulation
from financial_sim.simulation.snapshot import SnapshotError, StateSnapshot


@pytest.fixture
def sim() -> Simulation:
    s = Simulation(SimConfig(n_households=20, n_ticks=24), seed=123)
    s.run(n_ticks=5)
    return s


def test_roundtrip_equal_state(sim, tmp_path):
    path = tmp_path / "snap.json"
    StateSnapshot.save(sim, path)
    restored = StateSnapshot.load(path)

    a, b = sim.state, restored.state
    assert a.t == b.t
    assert abs(a.real_gdp - b.real_gdp) < 1e-9
    assert abs(a.price_level - b.price_level) < 1e-12
    assert len(a.households) == len(b.households)
    for ha, hb in zip(a.households, b.households, strict=True):
        assert (ha.id, round(ha.deposits, 12)) == (hb.id, round(hb.deposits, 12))
    assert abs(a.bank.capital - b.bank.capital) < 1e-12
    assert abs(a.government.debt - b.government.debt) < 1e-9
    assert abs(a.central_bank.gov_bonds - b.central_bank.gov_bonds) < 1e-9
    assert abs(b.inflation_expectation.value - a.inflation_expectation.value) < 1e-12
    assert len(a.macro_history) == len(b.macro_history)


def test_restored_sim_continues_without_sfc_violation(sim, tmp_path):
    path = tmp_path / "snap.json"
    StateSnapshot.save(sim, path)
    restored = StateSnapshot.load(path)
    restored.run(n_ticks=12)
    assert sum(len(v) for v in restored.state.sfc_violations) == 0


def test_version_mismatch_raises(sim, tmp_path):
    import json
    path = tmp_path / "bad.json"
    payload = {"_version": -999}
    path.write_text(json.dumps(payload))
    with pytest.raises(SnapshotError):
        StateSnapshot.load(path)


def test_same_seed_reproduces_identical_path(tmp_path):
    """同 seed 两个仿真应逐 tick 一致 (RNGManager 决定论)."""
    cfg = SimConfig(n_households=30, n_ticks=6)
    r1 = Simulation(cfg, seed=9)
    r1.run(10)
    r2 = Simulation(cfg, seed=9)
    r2.run(10)
    assert abs(r1.state.bank.capital - r2.state.bank.capital) < 1e-9
    assert abs(r1.state.price_level - r2.state.price_level) < 1e-12
