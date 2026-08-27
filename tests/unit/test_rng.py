"""RNGManager 测试: 可复现性 + 流独立性."""
from __future__ import annotations

import numpy as np

from financial_sim.simulation.rng import RNGManager, make_rng


class TestDeterminism:
    """同 seed 完全复现."""

    def test_same_seed_same_sequence(self):
        a = RNGManager(seed=42).stream("test")
        b = RNGManager(seed=42).stream("test")
        assert np.array_equal(a.random(10), b.random(10))

    def test_different_seed_different_sequence(self):
        a = RNGManager(seed=42).stream("test")
        b = RNGManager(seed=43).stream("test")
        assert not np.array_equal(a.random(10), b.random(10))


class TestStreamIndependence:
    """流之间互不影响."""

    def test_streams_are_independent(self):
        mgr_a = RNGManager(seed=42)
        mgr_b = RNGManager(seed=42)

        # 在 mgr_a 中先抽 s1 再抽 s2; 在 mgr_b 中直接抽 s2
        _ = mgr_a.stream("s1").random(5)
        from_a_s2 = mgr_a.stream("s2").random(5)
        from_b_s2 = mgr_b.stream("s2").random(5)
        assert np.array_equal(from_a_s2, from_b_s2)

    def test_stream_reuse_same_generator(self):
        mgr = RNGManager(seed=1)
        assert mgr.stream("x") is mgr.stream("x")


class TestReset:
    """reset 后回到初始状态."""

    def test_reset_restores_sequence(self):
        mgr = RNGManager(seed=7)
        first = mgr.stream("a").random(3).copy()
        mgr.stream("a").random(100)  # 消耗掉
        mgr.reset()
        assert np.array_equal(mgr.stream("a").random(3), first)


class TestUsageReport:
    def test_usage_report_tracks(self):
        mgr = RNGManager(seed=1)
        mgr.track("household_init")
        mgr.track("household_init")
        report = mgr.usage_report()
        assert report["household_init"] == 2


def test_make_rng_stable():
    a = make_rng(42, "events")
    b = make_rng(42, "events")
    assert np.array_equal(a.random(5), b.random(5))
