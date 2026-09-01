"""Interbank network 动态化测试 (Phase 3.5 PR-4).

验收:
- 多银行 init: InterbankNetwork 已构造,edges 数 > 0
- 每家银行的 interbank_claims/debt 正确镜像 edges
- rewire: 季度触发,按 CAR 重排核心,清空并重建 edges
- rewire 不会破坏 per-bank BS 平衡
- 多银行 init 不会破坏 SFC
"""
from __future__ import annotations

import pytest

from financial_sim.agents.commercial_bank import CommercialBank
from financial_sim.config import SimConfig
from financial_sim.core.simulation import Simulation
from financial_sim.network.interbank import InterbankNetwork


@pytest.mark.unit
class TestInterbankNetworkRewire:
    """PR-4 核心: InterbankNetwork.rewire 行为."""

    def _make_banks(self, n_banks: int = 3, car: float = 0.15):
        """构造一组 BS 平衡的银行 (A=L+cap) with 目标 CAR."""
        banks = []
        for i in range(n_banks):
            b = CommercialBank(id=f"bank_{i + 1}", tier=1)
            # total_assets = reserves + loans = 1000
            # total_liabilities = deposits = 850
            # capital = 150 (CAR = 150/1000 = 0.15)
            b.reserves = 100.0
            b.loans_to_firms = 900.0  # total_assets = 1000
            b.deposits_from_hh = 850.0  # total_liabilities = 850
            b.capital = 150.0  # A - L = 150 ✓
            banks.append(b)
        return banks

    def test_build_core_periphery_creates_symmetric_edges(self):
        """核心内部全连接,对称敞口 (claims == debt per bank)."""
        rng = __import__("random").Random(42)
        net = InterbankNetwork.build_core_periphery(
            bank_ids=["b1", "b2", "b3"],
            core_size=3,
            link_density=0.5,
            avg_exposure=100.0,
            rng=rng,
        )
        # 3 节点全连接 = 3 * 2 = 6 个 edges (双向)
        assert len(net.exposures) == 6
        for (c, d), amt in net.exposures.items():
            # 对称
            assert net.exposures[(d, c)] == amt

    def test_rewire_clears_and_rebuilds(self):
        """rewire 清空旧 edges, 重建, 按 CAR 重排核心."""
        banks = self._make_banks(3)
        # bank_1 CAR=0.15, bank_2 CAR=0.15, bank_3 CAR=0.15 → 全核心
        rng = __import__("random").Random(42)
        net = InterbankNetwork.build_core_periphery(
            ["b1", "b2", "b3"], 3, 0.5, 100.0, rng=rng
        )
        initial_edges = set(net.exposures.keys())
        # 触发 rewire
        net.rewire(
            banks=banks, core_size=2, link_density=0.5,
            avg_exposure=80.0, rng=rng, current_t=3
        )
        # edges 数应改变 (新 avg_exposure 不同)
        # 至少: 应有 1 个 core(2 banks) + 1 个 periphery(1 bank)
        # 核心内部全连接 = 1 edge pair (2 edges)
        assert len(net.exposures) >= 2
        # 核心集合
        assert len(net.core_ids) == 2
        # bank 同步: 每个核心 bank 在 core_ids 中
        for b in banks:
            if b.id in net.core_ids:
                assert b.interbank_claims > 0
                assert b.interbank_debt > 0

    def test_rewire_preserves_per_bank_bs(self):
        """rewire 后 per-bank BS 仍平衡 (A=L+cap)."""
        banks = self._make_banks(3)
        bank_ids = [b.id for b in banks]
        for b in banks:
            a = b.total_assets()
            l = b.total_liabilities()
            assert a == pytest.approx(l + b.capital, abs=1e-9)
        rng = __import__("random").Random(42)
        net = InterbankNetwork.build_core_periphery(
            bank_ids, 3, 0.5, 100.0, rng=rng
        )
        # 同步银行
        bank_by_id = {b.id: b for b in banks}
        for (c, d), amt in net.exposures.items():
            bank_by_id[c].interbank_claims += amt
            bank_by_id[d].interbank_debt += amt
        # 验证 rewire 前 balance
        for b in banks:
            a = b.total_assets()
            l = b.total_liabilities()
            assert a == pytest.approx(l + b.capital, abs=1e-9), \
                f"Pre-rewire imbalance at {b.id}"
        # rewire
        net.rewire(
            banks=banks, core_size=3, link_density=0.5,
            avg_exposure=100.0, rng=rng, current_t=3
        )
        # 验证 rewire 后仍 balance
        for b in banks:
            a = b.total_assets()
            l = b.total_liabilities()
            assert a == pytest.approx(l + b.capital, abs=1e-9), \
                f"Post-rewire imbalance at {b.id}"

    def test_rewire_dedup_per_tick(self):
        """同 tick 重复 rewire 不重复触发 (last_rewire_t 防重复)."""
        banks = self._make_banks(3)
        rng = __import__("random").Random(42)
        net = InterbankNetwork.build_core_periphery(
            ["b1", "b2", "b3"], 3, 0.5, 100.0, rng=rng
        )
        initial_t = net.last_rewire_t
        net.rewire(banks, 3, 0.5, 100.0, rng, current_t=5)
        first_edges = set(net.exposures.keys())
        # 同 tick 再次调用应 no-op
        net.rewire(banks, 3, 0.5, 100.0, rng, current_t=5)
        assert set(net.exposures.keys()) == first_edges


@pytest.mark.integration
class TestInterbankInitMultiBank:
    """PR-4 init: 多银行时自动启用 InterbankNetwork."""

    def test_multi_bank_init_enables_interbank_network(self):
        cfg = SimConfig(n_households=100, n_banks=3, n_ticks=1, seed=42)
        sim = Simulation(cfg)
        assert sim.state.interbank_network is not None
        assert len(sim.state.interbank_network.exposures) > 0

    def test_single_bank_no_interbank_network(self):
        """单银行 (n_banks=1) 维持 InterbankNetwork=None (向后兼容)."""
        cfg = SimConfig(n_households=100, n_banks=1, n_ticks=1, seed=42)
        sim = Simulation(cfg)
        assert sim.state.interbank_network is None

    def test_interbank_init_balanced_sfc(self):
        """多银行 init 后 SFC 干净."""
        cfg = SimConfig(n_households=200, n_banks=3, n_ticks=1, seed=42)
        sim = Simulation(cfg)
        bs = sim.state.build_balance_sheets()
        from financial_sim.monetary.sfc import validate_sfc
        errors = validate_sfc(bs)
        assert errors == [], f"SFC violations at init: {errors}"

    def test_interbank_init_each_bank_balanced(self):
        """每家银行 init 后 per-bank BS 平衡."""
        cfg = SimConfig(n_households=200, n_banks=3, n_ticks=1, seed=42)
        sim = Simulation(cfg)
        for b in sim.state.banks:
            a = b.total_assets()
            l = b.total_liabilities()
            assert a == pytest.approx(l + b.capital, abs=1e-9), \
                f"{b.id}: A={a}, L={l}, cap={b.capital}"

    def test_interbank_init_runs_12_ticks_clean(self):
        """多银行 init 后跑 12 tick SFC 干净 (rewire 触发但不破坏)."""
        cfg = SimConfig(n_households=200, n_banks=3, n_ticks=12, seed=42)
        sim = Simulation(cfg)
        sim.run(12)
        total = sum(len(v) for v in sim.state.sfc_violations)
        assert total == 0, f"SFC violations: {sim.state.sfc_violations[:2]}"

    def test_rewire_fires_at_configured_frequency(self):
        """rewire_freq=3: 应在 t=3,6,9 触发 rewire."""
        cfg = SimConfig(
            n_households=100, n_banks=3, n_ticks=12,
            seed=42, interbank_rewire_freq=3,
        )
        sim = Simulation(cfg)
        sim.run(12)
        assert sim.state.interbank_network.last_rewire_t == 9  # 最后一次 at t=9
        # 初始 t=-1, rewire fires at t=3,6,9. last_rewire_t=9.

    def test_rewire_freq_disabled(self):
        """interbank_rewire_freq=0: 禁用 rewire."""
        cfg = SimConfig(
            n_households=100, n_banks=3, n_ticks=12,
            seed=42, interbank_rewire_freq=0,
        )
        sim = Simulation(cfg)
        sim.run(12)
        assert sim.state.interbank_network.last_rewire_t == -1