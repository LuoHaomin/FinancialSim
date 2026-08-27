"""Phase 3 Week C 单元测试: Brock-Hommes 股票市场."""
from __future__ import annotations

import numpy as np
import pytest

import financial_sim.core.simulation  # noqa: F401  (先断开循环导入)
from financial_sim.markets.stocks import StockMarket, Trader


def _market(**overrides) -> StockMarket:
    class C:  # 最小 config 桩
        pass
    c = C()
    defaults: dict = {
        "stock_liquidity_lambda": 0.40, "stock_depth": 10.0,
        "stock_cost_of_trading": 0.001, "stock_order_fraction": 0.15,
        "bh_temperature": 1.0, "bh_fitness_decay": 0.05,
        "stock_substeps_per_month": 4, "cb_neutral_rate": 0.02,
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(c, k, v)
    m = StockMarket.from_config(c, traders_n=4)
    m.supply_units = 3000.0
    m.price = 10.0
    m.price_history = [10.0]
    return m


class TestBeliefRules:
    def test_forecast_values(self):
        tr = Trader(id="t")
        rng = np.random.default_rng(0)
        # p=100, prev=90 → trend 预测 110
        preds = tr.forecasts(price=100.0, prev_price=90.0, ma_price=95.0,
                             fundamental=120.0, rng=rng)
        assert preds[0] == pytest.approx(105.0)   # R1 trend = 100+0.5×(100−90)
        assert preds[1] == pytest.approx(120.0)   # R2 fundamental
        assert preds[2] == pytest.approx(95.0)    # R3 mean reversion
        assert preds[3] == pytest.approx(100.0)   # R4 adaptive (首期无历史)
        assert preds[4] == pytest.approx(105.0)   # R5 optimistic
        assert preds[5] == pytest.approx(95.0)    # R6 pessimistic
        assert abs(preds[6] - 100.0) < 5.0        # R7 noise 界内

    def test_adaptive_rule_uses_its_own_state(self):
        tr = Trader(id="t")
        tr.adaptive_forecast = 80.0               # R4 上期预测
        rng = np.random.default_rng(0)
        preds = tr.forecasts(100.0, 90.0, 95.0, 120.0, rng)
        assert preds[3] == pytest.approx(0.5 * 100 + 0.5 * 80)


class TestVirtualPnlFitness:
    def test_correct_direction_gains_fitness(self):
        tr = Trader(id="t")
        preds = np.array([120.0, 100.0, 120.0, 100.0, 120.0, 100.0, 100.0])
        old, new = 100.0, 102.0                   # 实际涨 2%
        tr.update_fitness(preds, old, new)
        # 看多规则 (预测>旧价) 得正分, 看空得负分
        assert tr.fitness[0] == pytest.approx(0.02)
        assert tr.fitness[1] == pytest.approx(0.0)  # 预测==现价: 零方向不计分

    def test_decay_applies(self):
        tr = Trader(id="t")
        tr.fitness[:] = 10.0
        preds = np.array([100.0] * 7)
        tr.update_fitness(preds, 100.0, 100.0)    # 无涨跌: 只衰减
        assert np.allclose(tr.fitness, 10.0 * 0.95)

    def test_contribution_capped(self):
        tr = Trader(id="t")
        preds = np.array([1000.0] * 7)            # 全体极端看多
        tr.update_fitness(preds, 10.0, 100.0)     # r = 900%
        assert np.all(tr.fitness <= 0.10 + 1e-12)


class TestMarketMechanics:
    def test_price_converges_toward_fundamental(self):
        """股息锚定的基本面远高于现价时, 市场应逐步上行."""
        m = _market()
        rng = np.random.default_rng(42)
        start = m.price                            # 10
        # 基本面 = 0.6/0.05 = 12 → 应上行 (允许噪声波动)
        for _ in range(48):
            m.step_month(annual_dividend_per_share=0.6, rng=rng)
        assert m.price > start * 0.99              # 不应系统性崩溃

    def test_price_history_recorded(self):
        m = _market()
        m.step_month(0.6, np.random.default_rng(0))
        assert len(m.price_history) == 2
        assert m.price > 0

    def test_no_trades_when_supply_zero(self):
        m = _market()
        m.supply_units = 0.0
        res = m.step_month(0.6, np.random.default_rng(0))
        assert res["net_flow_units"] == 0.0
