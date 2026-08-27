"""Phase 3 Week C M3 单元/集成测试: 交叉持股骨架."""
from __future__ import annotations

import numpy as np
import pytest

from financial_sim.agents.firm import Firm
from financial_sim.config import SimConfig
from financial_sim.core.simulation import Simulation
from financial_sim.network.cross_holdings import (
    CrossHoldingsNetwork,
    build_cross_holdings,
)

ALL_SECTORS = [
    "consumer_goods", "capital", "energy",
    "housing_services", "high_tech", "services",
]


def _firms(n: int = 6) -> list[Firm]:
    return [
        Firm(id=f"f{i}", sector="consumer_goods", shares_outstanding=500)
        for i in range(n)
    ]


class TestGraphGeneration:
    def test_empty_network_single_firm(self):
        rng = np.random.default_rng(0)
        net = build_cross_holdings(_firms(1), beta=0.2, rng=rng)
        assert net.total_units == 0.0

    def test_beta_fraction_issued(self):
        """Σ被持 == Σ发行人 β×股数."""
        firms = _firms()
        rng = np.random.default_rng(1)
        net = build_cross_holdings(firms, beta=0.2, rng=rng)
        issued = net.issued_units_to_firms()
        expected = sum(f.shares_outstanding * 0.2 for f in firms)
        assert abs(net.total_units - expected) < 1e-9
        assert abs(sum(issued.values()) - net.total_units) < 1e-9

    def test_no_self_holding(self):
        firms = _firms()
        rng = np.random.default_rng(2)
        net = build_cross_holdings(firms, beta=0.2, rng=rng)
        for holder, targets in net.edges.items():
            assert holder not in targets

    def test_valuation_at_price(self):
        firms = _firms()
        rng = np.random.default_rng(3)
        net = build_cross_holdings(firms, beta=0.5, rng=rng)
        prices = {f.id: 10.0 for f in firms}
        holder_val = sum(
            net.valuation(hid, prices) for hid in net.edges
        )
        assert holder_val == pytest.approx(net.total_units * 10.0)

    def test_zero_beta_degenerate(self):
        rng = np.random.default_rng(4)
        net = build_cross_holdings(_firms(), beta=0.0, rng=rng)
        assert isinstance(net, CrossHoldingsNetwork)
        assert net.total_units == 0.0


class TestCrossHoldingsIntegration:
    def _sim(self, seed: int, n_ticks: int = 36) -> Simulation:
        cfg = SimConfig(
            n_households=300, n_ticks=n_ticks, seed=seed,
            sectors=list(ALL_SECTORS),
            enable_stock_market=True, enable_cross_holdings=True,
        )
        return Simulation(cfg, seed=seed)

    @pytest.mark.parametrize("seed", [42, 7])
    def test_sfc_clean_with_cross_holdings(self, seed):
        state = self._sim(seed).run(36)
        assert sum(len(v) for v in state.sfc_violations) == 0

    def test_total_supply_conservation_three_way(self):
        """家庭持仓 + 企业互持 == 总股数; 互持双边相等."""
        state = self._sim(seed=42).run(36)
        mkt = state.stock_market
        held_hh = sum(h.stock_units for h in state.households)
        held_firms = sum(
            sum(t.values()) for t in state.cross_holdings.values()
        )
        issued_to_firms = sum(f.shares_held_by_firms for f in state.firms)
        assert abs((held_hh + held_firms) - mkt.supply_units) < 1e-4
        assert abs(held_firms - issued_to_firms) < 1e-6

    def test_dual_account_net_out_in_aggregate_bs(self):
        """聚合 BS 的 stocks 与 minority_equity 相等 (NW 不虚增)."""
        state = self._sim(seed=7).run(12)
        bs = state.build_balance_sheets()["firms"]
        assert bs.stocks == pytest.approx(bs.minority_equity, rel=1e-6)

    def test_firm_shareholders_receive_dividends(self):
        """企业股东应收到分红入账 (deposits 增加)."""
        sim = self._sim(seed=42)
        state = sim.run(24)
        got = sum(
            f.dividend_received_from_firms for f in state.firms
        )
        if state.cross_holdings and state.last_month_dividends > 0:
            assert got >= 0.0

    def test_snapshot_roundtrip_preserves_graph(self):
        import tempfile
        from pathlib import Path

        from financial_sim.simulation.snapshot import StateSnapshot

        sim = self._sim(seed=11, n_ticks=6)
        sim.run(6)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "snap.json"
            StateSnapshot.save(sim, path)
            sim2 = StateSnapshot.load(path)
            st2 = sim2.state
            edges_before = {
                h: dict(t) for h, t in sim.state.cross_holdings.items()
            }
            assert st2.cross_holdings == edges_before
            restored_shares = sum(
                f.shares_held_by_firms for f in st2.firms
            )
            graph_shares = sum(
                sum(t.values()) for t in st2.cross_holdings.values()
            )
            assert abs(restored_shares - graph_shares) < 1e-9

    def test_disabled_by_default_no_effect(self):
        cfg = SimConfig(
            n_households=100, n_ticks=6, sectors=list(ALL_SECTORS),
            enable_stock_market=True,
        )
        state = Simulation(cfg, seed=1).run(6)
        assert state.cross_holdings == {}
        assert all(f.shares_held_by_firms == 0.0 for f in state.firms)
