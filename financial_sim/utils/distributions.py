"""异质性分布工具.

Phase 1 Week 7 的 "5 个分布": 初始化家庭/企业时从这些分布抽样,
全部走 RNGManager 命名流, 保证同 seed 复现.
"""
from __future__ import annotations

import numpy as np


def lognormal_from_median(
    rng: np.random.Generator,
    median: float,
    sigma: float,
    size: int | None = None,
) -> float | np.ndarray:
    """对数正态分布, 以中位数和形状参数 σ 参数化.

    SCF 2019: 家庭财富 ≈ LogNormal(median≈$100k, σ≈1.3) + 帕累托尾.
    Phase 1 先用纯 LogNormal, 帕累托尾 Phase 2 加.
    """
    mu = float(np.log(median))
    sample = rng.lognormal(mean=mu, sigma=sigma, size=size)
    if size is None:
        out: float | np.ndarray = float(sample)
    else:
        out = sample
    return out


def truncated_normal(
    rng: np.random.Generator,
    mean: float,
    std: float,
    low: float,
    high: float,
    size: int | None = None,
) -> float | np.ndarray:
    """截断正态. 用于储蓄率、MPC 等 [0, 1] 区间参数.

    实现: 正态抽样后重抽样落入区间的点 (拒绝采样),
    std << (high-low) 时开销可忽略.
    """
    size_arg = None if size is None else int(size)
    out_list: list[float] = []
    remaining = size_arg
    while remaining is None or remaining > 0:
        n = 1 if remaining is None else max(remaining, 1)
        candidates = rng.normal(loc=mean, scale=std, size=n)
        accepted = [c for c in candidates if low <= c <= high]
        out_list.extend(accepted)
        drawn = len(accepted)
        if remaining is None:
            if drawn > 0:
                return out_list[0]
            continue
        remaining -= drawn
    result: np.ndarray = np.array(out_list[:size], dtype=float)
    return result


def beta_scaled(
    rng: np.random.Generator,
    alpha: float,
    beta_param: float,
    scale: float = 1.0,
    size: int | None = None,
) -> float | np.ndarray:
    """缩放的 Beta 分布. 用于风险容忍度等有界参数."""
    sample = rng.beta(alpha, beta_param, size=size)
    if size is None:
        out: float | np.ndarray = float(sample) * scale
    else:
        out = sample * scale
    return out


__all__ = ["lognormal_from_median", "truncated_normal", "beta_scaled"]
