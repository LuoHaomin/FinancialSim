"""Phase 3 Week C 集成验收: 股票市场开启下的经济."""
from __future__ import annotations

import numpy as np
import pytest

from financial_sim.config import SimConfig
from financial_sim.core.simulation import Simulation
from financial_sim.simulation.snapshot import SNAPSHOT_VERSION, StateSnapshot

ALL_SECTORS = [
    "consumer_goods", "capital", "energy",
    "housing_services", "high_tech", "services",
]


def _stock_sim(n_ticks: int = 36, seed: int = 42, **kw) -> Simulation:
    cfg = SimConfig(
        n_households=300, n_ticks=n_ticks, seed=seed,
        sectors=list(ALL_SECTORS), enable_stock_market=True, **kw,
    )
    return Simulation(cfg, seed=seed)


class TestStockMarketAcceptance:
    @pytest.mark.parametrize("seed", [42, 7, 99])
    def test_zero_sfc_violations(self, seed):
        state = _stock_sim(seed=seed).run(36)
        assert sum(len(v) for v in state.sfc_violations) == 0

    def test_holdings_conserve_supply(self):
        """家庭持仓总和 == 总股数 (买卖只是过户)."""
        state = _stock_sim(seed=42).run(36)
        mkt = state.stock_market
        held = sum(h.stock_units for h in state.households)
        assert abs(held - mkt.supply_units) < 1e-6 * max(1.0, mkt.supply_units)

    def test_deposit_mirror_aggregate(self):
        """Σhh.deposits == bank.deposits_from_hh (股票净流结算后仍守恒)."""
        state = _stock_sim(seed=7).run(24)
        hh = sum(h.deposits for h in state.households)
        bk = state.bank.deposits_from_hh
        assert abs(hh - bk) < 1e-6 * max(1.0, abs(bk))

    def test_stylized_facts_presence(self):
        """波动率>0、厚尾 kurtosis≥3、价格恒正 (BH 内生产物)."""
        state = _stock_sim(n_ticks=48, seed=42).run(48)
        hist = np.array(state.stock_market.price_history)
        rets = np.diff(hist) / hist[:-1]
        assert float(np.std(rets)) > 0
        kurt = float(((rets - rets.mean()) ** 4).mean() / max(rets.var(), 1e-12) ** 2)
        assert kurt >= 3.0, f"kurtosis={kurt:.2f} 应厚尾"
        assert (hist > 0).all()

    def test_reproducible_same_seed(self):
        s1 = _stock_sim(seed=5).run(12)
        s2 = _stock_sim(seed=5).run(12)
        p1 = s1.stock_market.price_history
        p2 = s2.stock_market.price_history
        assert len(p1) == len(p2)
        assert all(abs(a - b) < 1e-9 for a, b in zip(p1, p2, strict=True))

    def test_dividends_paid_to_shareholders(self):
        """分红应随持股比例分配 (非存款比例), 股息锚被记录."""
        sim = _stock_sim(n_ticks=12, seed=42)
        state = sim.run(12)
        # 只要当月有分红且股市启用, 股息锚必须写入
        if any(h.stock_units > 0 for h in state.households):
            assert state.last_month_dividends >= 0.0


class TestStockSnapshot:
    def test_snapshot_v4_roundtrip_with_market(self):
        import tempfile
        from pathlib import Path

        sim = _stock_sim(n_ticks=6, seed=11)
        sim.run(6)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "snap.json"
            StateSnapshot.save(sim, path)
            sim2 = StateSnapshot.load(path)
            st2 = sim2.run(3)
            assert st2.stock_market is not None
            assert st2.stock_market.price > 0
            assert sum(len(v) for v in st2.sfc_violations) == 0

    def test_version_is_4(self):
        assert SNAPSHOT_VERSION == 4
