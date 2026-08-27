"""通胀预期模块.

Phase 1: 适应性预期 (指数滑动平均) + 通胀锚定机制.
脱锚 (de-anchoring): 实际通胀持续偏离目标过远、过久时, 预期脱离锚.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class InflationExpectation:
    """聚合通胀预期形成器 (家庭/企业可各自实例化; Phase 2 异质化)."""

    value: float = 0.02                  # 当前预期 (年化)
    adapt_speed: float = 0.3             # 适应性更新速度 α
    anchor: float = 0.02                 # 锚 = 央行通胀目标
    anchor_weight: float = 0.3           # 每期向锚回归的权重
    deanchor_threshold: float = 0.06     # |实际 − 目标| 超过此值开始脱锚
    deanchor_persistence: int = 6        # 连续 N 个月超阈值才脱锚
    _exceed_streak: int = 0              # 内部: 连续超阈值月数

    def update(self, realized_inflation: float, target_inflation: float | None = None) -> None:
        """每月调用一次: 适应性更新 + 锚回归 + 脱锚判定."""
        target = target_inflation if target_inflation is not None else self.anchor
        gap = abs(realized_inflation - target)

        if gap > self.deanchor_threshold:
            self._exceed_streak += 1
            anchored = self._exceed_streak < self.deanchor_persistence
        else:
            self._exceed_streak = 0
            anchored = True

        a = min(1.0, max(0.0, self.adapt_speed))
        w = min(1.0, max(0.0, self.anchor_weight)) if anchored else 0.0

        adapted = self.value + a * (realized_inflation - self.value)
        self.value = adapted + w * (target - adapted)

    def reset(self, initial_value: float = 0.02) -> None:
        """重置到初始状态."""
        self.value = initial_value
        self._exceed_streak = 0


__all__ = ["InflationExpectation"]
