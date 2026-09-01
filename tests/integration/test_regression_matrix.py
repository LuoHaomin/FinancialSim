"""Phase 3.5 PR-6: 完整回归矩阵 — 7 场景 × 3 种子, NBFI 全开默认体制.

锁两件事 (见 AGENTS.md §3.4 / §6):
1. SFC 一致性: 全矩阵零违反 (PR-5 修复后的记账性质).
2. 可复现性: 同 seed 逐位一致 (golden 值锁定; 行为有意变更时须显式更新).

⚠️ 已知行为失真 (PR-7 课题, 本文件刻意不作为门禁):
- 非 baseline 场景的财政/货币冲击对 real_gdp 几乎无影响 (劳动需求渠道
  被全开模块捂住; 冲击通道本身 verified: 乘数/房价/银行失败均生效).
- stagflation 全开下企业全灭 (u→1, gdp→0): 能源冲击 × 单企业部门
  轮盘赌 × 供应链成本, 经济无恢复路径.
golden 值按 PR-5 完成时的全开体制采集 (2026-09).
"""
from __future__ import annotations

import math

import pytest

from financial_sim.core.simulation import Simulation
from financial_sim.scenarios import list_scenarios, load_scenario

SEEDS = [7, 42, 99]
MAX_TICKS = 240  # baseline (1200) 截断, 控制矩阵耗时

# (scenario, seed) → (real_gdp_end, u_end, u_max, sfc_violations)
GOLDEN: dict[tuple[str, int], tuple[float, float, float, int]] = {
    # baseline 2026-09-01 重采: PR-7 第二期校准 (多部门 + 财政可持续
    # G=0.40/τ=0.35 + potential_gdp 随 TFP 增长修复 Taylor 加息雪崩)
    ("baseline", 7): (1356.8599, 0.0, 0.492, 0),
    ("baseline", 42): (1344.8775, 0.0, 0.501, 0),
    ("baseline", 99): (1337.8212, 0.0, 0.518, 0),
    ("crisis_2008", 7): (218.8201, 0.0, 0.005, 0),
    ("crisis_2008", 42): (218.8201, 0.0, 0.0, 0),
    ("crisis_2008", 99): (218.8201, 0.0, 0.005, 0),
    ("housing_bust", 7): (218.8201, 0.0, 0.005, 0),
    ("housing_bust", 42): (218.8201, 0.0, 0.0, 0),
    ("housing_bust", 99): (218.8201, 0.0, 0.005, 0),
    ("loose_credit", 7): (218.8201, 0.0, 0.005, 0),
    ("loose_credit", 42): (218.8201, 0.0, 0.0, 0),
    ("loose_credit", 99): (218.8201, 0.0, 0.005, 0),
    ("post_war_recovery", 7): (218.8201, 0.0, 0.005, 0),
    ("post_war_recovery", 42): (218.8201, 0.0, 0.0, 0),
    ("post_war_recovery", 99): (218.8201, 0.0, 0.005, 0),
    ("stagflation", 7): (0.0, 1.0, 1.0, 0),
    ("stagflation", 42): (0.0, 1.0, 1.0, 0),
    ("stagflation", 99): (0.0, 1.0, 1.0, 0),
    ("tight_credit", 7): (214.9195, 0.0, 0.005, 0),
    ("tight_credit", 42): (214.9195, 0.0, 0.0, 0),
    ("tight_credit", 99): (214.9195, 0.0, 0.005, 0),
}


def _run(name: str, seed: int) -> Simulation:
    cfg, _overrides = load_scenario(name)
    n_ticks = min(cfg.n_ticks, MAX_TICKS)
    cfg = cfg.model_copy(update={"seed": seed, "n_ticks": n_ticks})
    sim = Simulation(cfg, seed=seed)
    sim.run(n_ticks)
    return sim


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("name", list_scenarios())
class TestRegressionMatrix:
    def test_zero_sfc_violations(self, name: str, seed: int):
        sim = _run(name, seed)
        assert sum(len(v) for v in sim.state.sfc_violations) == 0

    def test_key_moments_finite_and_bounded(self, name: str, seed: int):
        sim = _run(name, seed)
        st = sim.state
        assert math.isfinite(st.real_gdp)
        assert 0.0 <= st.unemployment_rate <= 1.0
        for s in st.macro_history:
            assert math.isfinite(s.unemployment_rate)
            assert math.isfinite(s.real_gdp)

    def test_golden_reproducibility(self, name: str, seed: int):
        """同 seed 同场景逐位复现 (golden 锁定, 行为变更须显式更新)."""
        sim = _run(name, seed)
        st = sim.state
        u_max = max(s.unemployment_rate for s in st.macro_history)
        got = (
            round(st.real_gdp, 4),
            round(st.unemployment_rate, 4),
            round(u_max, 4),
            sum(len(v) for v in st.sfc_violations),
        )
        expected = GOLDEN.get((name, seed))
        assert expected is not None, f"缺少 golden: {(name, seed)}"
        assert got == expected
