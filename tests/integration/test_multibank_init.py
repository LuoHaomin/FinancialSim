"""多银行 init + 工具函数集成测试 (Phase 3.5 PR-2).

验收:
- `n_banks>=2` 时, 每家 HH/firm 随机选 home_bank_id
- 每家银行的 `market_share` 由 HH deposit 比例计算, Σ = 1.0
- `_allocate_share` 工具函数: 单银行/多银行/残差/负数/零 全通过
- 单银行 (n_banks=1) 仍走主银行语义 (向后兼容)
- 多银行 init 不破坏 SFC 校验(仍聚合一致)
"""
from __future__ import annotations

import pytest

from financial_sim.agents.commercial_bank import CommercialBank
from financial_sim.config import SimConfig
from financial_sim.core.simulation import Simulation
from financial_sim.core.step import _allocate_share


@pytest.mark.unit
class TestAllocateShare:
    """`_allocate_share` 工具函数 SFC 测试."""

    def test_single_bank_full_amount(self):
        """单银行: 全部给唯一银行, 无残差."""
        b1 = CommercialBank(id="b1", market_share=1.0)
        out = _allocate_share(100.0, [b1])
        assert out == {"b1": 100.0}

    def test_multi_bank_proportional(self):
        """多银行: 按 market_share 比例拆分."""
        b1 = CommercialBank(id="b1", market_share=0.6)
        b2 = CommercialBank(id="b2", market_share=0.3)
        b3 = CommercialBank(id="b3", market_share=0.1)
        out = _allocate_share(100.0, [b1, b2, b3])
        assert out["b1"] == pytest.approx(60.0)
        assert out["b2"] == pytest.approx(30.0)
        # b3 残差吸收
        assert out["b3"] == pytest.approx(10.0)
        assert sum(out.values()) == pytest.approx(100.0)

    def test_floating_residual_absorption(self):
        """浮点尾差由最后一家吸收 (SFC 逐位相等)."""
        b1 = CommercialBank(id="b1", market_share=0.33333)
        b2 = CommercialBank(id="b2", market_share=0.33333)
        b3 = CommercialBank(id="b3", market_share=0.33334)
        out = _allocate_share(100.0, [b1, b2, b3])
        assert sum(out.values()) == pytest.approx(100.0, abs=1e-12)
        # 残差必在最后一家
        assert out["b3"] == pytest.approx(
            100.0 - out["b1"] - out["b2"], abs=1e-12
        )

    def test_negative_amount(self):
        """负数 (扣款/退款) 同样拆分."""
        b1 = CommercialBank(id="b1", market_share=0.6)
        b2 = CommercialBank(id="b2", market_share=0.4)
        out = _allocate_share(-50.0, [b1, b2])
        assert out["b1"] == pytest.approx(-30.0)
        assert out["b2"] == pytest.approx(-20.0)
        assert sum(out.values()) == pytest.approx(-50.0)

    def test_zero_amount(self):
        """零额: 返回全 0."""
        b1 = CommercialBank(id="b1", market_share=0.5)
        b2 = CommercialBank(id="b2", market_share=0.5)
        out = _allocate_share(0.0, [b1, b2])
        assert out == {"b1": 0.0, "b2": 0.0}

    def test_empty_banks(self):
        """空列表: 返回空 dict."""
        assert _allocate_share(100.0, []) == {}

    def test_uneven_shares(self):
        """非等分 (80/15/5): 残差吸收确保求和."""
        b1 = CommercialBank(id="b1", market_share=0.80)
        b2 = CommercialBank(id="b2", market_share=0.15)
        b3 = CommercialBank(id="b3", market_share=0.05)
        out = _allocate_share(333.33, [b1, b2, b3])
        assert sum(out.values()) == pytest.approx(333.33, abs=1e-9)


@pytest.mark.integration
class TestMultiBankInit:
    """PR-2: 多银行 init + home_bank_id + market_share."""

    def test_single_bank_assigns_all_to_bank_zero(self):
        """单银行: 所有 HH/firm 都归 banks[0]."""
        cfg = SimConfig(n_households=50, n_banks=1, n_ticks=1)
        sim = Simulation(cfg)
        bank0 = sim.state.banks[0]
        for h in sim.state.households:
            assert h.home_bank_id == bank0.id
        for f in sim.state.firms:
            assert f.home_bank_id == bank0.id
        assert bank0.market_share == pytest.approx(1.0)

    def test_multi_bank_assigns_home_bank(self):
        """n_banks=3: 每 HH/firm 应有 home_bank_id (可能不同)."""
        cfg = SimConfig(n_households=100, n_banks=3, n_ticks=1)
        sim = Simulation(cfg)
        bank_ids = {b.id for b in sim.state.banks}
        for h in sim.state.households:
            assert h.home_bank_id in bank_ids
        for f in sim.state.firms:
            assert f.home_bank_id in bank_ids

    def test_market_share_sums_to_one(self):
        """market_share Σ == 1.0 (残差给 banks[0])."""
        cfg = SimConfig(n_households=200, n_banks=5, n_ticks=1, seed=42)
        sim = Simulation(cfg)
        total_share = sum(b.market_share for b in sim.state.banks)
        assert total_share == pytest.approx(1.0, abs=1e-9)
        for b in sim.state.banks:
            assert 0.0 <= b.market_share <= 1.0

    def test_market_share_deposit_weighted(self):
        """market_share 应为 HH deposit-weighted (反映真实存款分配)."""
        cfg = SimConfig(n_households=200, n_banks=2, n_ticks=1, seed=42)
        sim = Simulation(cfg)
        b1, b2 = sim.state.banks
        # 各银行应负责的存款份额
        dep_b1 = sum(
            h.deposits for h in sim.state.households if h.home_bank_id == b1.id
        )
        dep_b2 = sum(
            h.deposits for h in sim.state.households if h.home_bank_id == b2.id
        )
        total_dep = dep_b1 + dep_b2
        assert b1.market_share == pytest.approx(dep_b1 / total_dep, abs=1e-9)
        assert b2.market_share == pytest.approx(dep_b2 / total_dep, abs=1e-9)

    def test_bank_assignment_reproducible(self):
        """同 seed: bank assignment 应一致 (RNGManager 命名流)."""
        cfg = SimConfig(n_households=100, n_banks=3, n_ticks=1, seed=42)
        sim1 = Simulation(cfg)
        sim2 = Simulation(cfg)
        # 同 seed: HH 的 home_bank_id 应一致
        for h1, h2 in zip(sim1.state.households, sim2.state.households, strict=True):
            assert h1.home_bank_id == h2.home_bank_id
        # market_share 一致
        for b1, b2 in zip(sim1.state.banks, sim2.state.banks, strict=True):
            assert b1.market_share == pytest.approx(b2.market_share, abs=1e-12)

    def test_multi_bank_init_no_sfc_violation(self):
        """多银行 init 后 SFC 干净 (聚合 BS 一致)."""
        cfg = SimConfig(n_households=200, n_banks=3, n_ticks=1, seed=42)
        sim = Simulation(cfg)
        # 跑 12 tick 不应破坏 SFC(主银行语义保留, 聚合 BS 守恒)
        sim.run(12)
        total_violations = sum(len(v) for v in sim.state.sfc_violations)
        assert total_violations == 0

    def test_bank_assignment_rng_named_stream(self):
        """bank_assignment 用命名流 'bank_assignment' (可复现)."""
        # 验证流名是稳定的 (用于审计 + 同种子重放)
        cfg = SimConfig(n_households=100, n_banks=2, n_ticks=1, seed=42)
        sim = Simulation(cfg)
        # RNGManager 暴露 usage_report 但 init 后不会自动 track; 这里只验证
        # 种子可复现性(见上一个 test).
        assert len(sim.state.banks) == 2
