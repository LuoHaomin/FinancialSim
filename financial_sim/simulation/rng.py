"""RNGManager: 命名随机流, 保证可复现性.

原则 (IMPLEMENTATION.md §1.1): 每个随机数必须来自命名流.
同一 seed 下, 流之间互不影响 — 在某个流中多抽一次不会改变其他流的序列.

用法:
    rng = RNGManager(seed=42)
    h_stream = rng.stream("household_init")
    shock_stream = rng.stream("events")
"""
from __future__ import annotations

from typing import Any

import numpy as np


class RNGManager:
    """按名字管理独立随机流.

    每个 stream 用 ``SeedSequence([seed, name_hash])`` 派生,
    保证不同 name 得到统计独立且可复现的序列.
    """

    def __init__(self, seed: int = 42) -> None:
        """初始化命名流管理器.

        Args:
            seed: 全局随机种子; 同一 seed 下, 各命名流派生出的子序列
                互相统计独立(由 SeedSequence + 字符串稳定哈希派生).
                默认 42 与 IMPLEMENTATION.md §1.1 约定的复现基线一致.
        """
        self.seed = seed
        self._streams: dict[str, np.random.Generator] = {}
        self._stream_calls: dict[str, int] = {}

    def stream(self, name: str) -> np.random.Generator:
        """获取(或创建)一个命名流."""
        if name not in self._streams:
            ss = np.random.SeedSequence([self.seed, _stable_hash(name)])
            self._streams[name] = np.random.default_rng(ss)
            self._stream_calls[name] = 0
        return self._streams[name]

    def track(self, name: str) -> None:
        """记录某流被使用过一次 (调试/审计用)."""
        self._stream_calls[name] = self._stream_calls.get(name, 0) + 1

    def usage_report(self) -> dict[str, int]:
        """各流的调用次数 (审计: 确认没有未命名 RNG)."""
        return dict(self._stream_calls)

    def reset(self) -> None:
        """重置所有流到初始状态. 同一 manager 可重放整个初始化过程."""
        self._streams.clear()
        self._stream_calls.clear()

    def spawn_child(self, seed_offset: int = 1) -> RNGManager:
        """派生一个子 manager (用于蒙特卡洛并行)."""
        return RNGManager(seed=self.seed + seed_offset)


def _stable_hash(name: str) -> int:
    """字符串 → 稳定整数 (跨进程一致, 不用 Python 内建 hash)."""
    return int.from_bytes(name.encode("utf-8"), "little") % (2**32)


def make_rng(seed: int, name: str) -> np.random.Generator:
    """便捷函数: 一次性创建命名流 (不需要复用时)."""
    ss = np.random.SeedSequence([seed, _stable_hash(name)])
    return np.random.default_rng(ss)


__all__: list[str | Any] = ["RNGManager", "make_rng"]
