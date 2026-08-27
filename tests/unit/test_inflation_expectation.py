"""InflationExpectation 测试: 适应性 + 锚定 + 脱锚."""
from __future__ import annotations

from financial_sim.expectations.inflation import InflationExpectation


class TestAdaptation:
    def test_moves_toward_realized(self):
        e = InflationExpectation(value=0.02, adapt_speed=0.5, anchor_weight=0.0,
                                 deanchor_threshold=1e9)  # 禁用锚以便观察纯适应性
        e.update(0.06, target_inflation=0.02)
        assert abs(e.value - 0.04) < 1e-9

    def test_anchor_pulls_back_to_target(self):
        e = InflationExpectation(value=0.02, adapt_speed=1.0, anchor_weight=0.5,
                                 deanchor_threshold=1e9)
        e.update(0.10, target_inflation=0.02)
        # adapted = 0.10; anchored 回归: 0.10 + 0.5×(0.02−0.10) = 0.06
        assert abs(e.value - 0.06) < 1e-9


class TestAnchoring:
    def test_stays_anchored_below_threshold(self):
        e = InflationExpectation(deanchor_threshold=0.06, deanchor_persistence=6)
        for _ in range(24):
            e.update(0.07)  # gap = 0.05 < 阈值
            assert abs(e.value - 0.02) < 0.03


class TestDeanchoring:
    def test_deanchors_after_persistence(self):
        e = InflationExpectation(value=0.02, adapt_speed=1.0, anchor_weight=0.5,
                                 deanchor_threshold=0.06, deanchor_persistence=6)
        for _ in range(12):
            e.update(0.20)  # gap=0.18 > 阈值, 连续超限
        # 脱锚后不再向锚回归, 应逼近实际通胀
        assert e.value > 0.15

    def test_streak_resets_on_return(self):
        e = InflationExpectation(deanchor_threshold=0.06, deanchor_persistence=6)
        for _ in range(5):
            e.update(0.20)
        e.update(0.02)  # gap=0 → streak 清零
        assert e._exceed_streak == 0


def test_reset():
    e = InflationExpectation(value=0.05)
    e.update(0.30)
    e.reset(initial_value=0.02)
    assert e.value == 0.02
    assert e._exceed_streak == 0
