"""Stock market: Brock-Hommes 异质信念 + 做市商出清 (Phase 3 Week C).

机制 (docs/EXPECTATIONS.md §9.1 + docs/MARKETS.md §4.4.1):
- 7 条信念规则 (趋势/基本面/均值回归/自适应/乐观/悲观/噪声)
- Trader 按 fitness softmax 选择信念, 预测误差更新适应度
- 做市商汇总超额需求调价: p ← p·(1 + λ·ED/depth)

SFC 注记 (IMPORTANT):
- 二级市场交易是**家庭部门内部**的存款转移 + 股票过户,
  聚合银行负债不变 (买卖双方都在家庭部门内轧平);
- 只有估值重估不入账; 净申购/赎回 (Δ持仓>0/<0) 才动家庭存款;
- 浮盈严禁变为购买力 — 只有过户清算产生的存款变动有效
  (2008 教训, test_crisis 守护).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

# ════════════════════════════════════════════════════════════
# 信念规则
# ════════════════════════════════════════════════════════════
TREND_COEFF = 0.5          # R1: f = p + 0.5·(p − p_prev)
MEAN_REV_WINDOW = 20       # R3: MA(p, window)
ADAPTIVE_ALPHA = 0.5       # R4: f = α·p + (1−α)·f_prev
SENTIMENT_BIAS = 0.05      # R5/R6: ±bias
NOISE_SIGMA = 0.02         # R7: ε ~ N(0, σ·p)


@dataclass
class Trader:
    """Brock-Hommes 交易者: 持有一组信念规则与各自适应度."""

    id: str
    # 价格历史由市场层统一提供; 这里只存每条规则的 fitness 与自适应预测值
    fitness: np.ndarray = field(default_factory=lambda: np.zeros(7))
    adaptive_forecast: float | None = None    # R4 状态
    last_rule_used: int = -1                  # 教学诊断

    def forecasts(self, price: float, prev_price: float,
                  ma_price: float, fundamental: float,
                  rng: np.random.Generator) -> np.ndarray:
        """7 条规则在当前信息集下的预测值.

        R2 基本面 = dividend_yield 锚定的贴现价值 (由市场层算好传入).
        """
        f_trend = price + TREND_COEFF * (price - prev_price)
        f_fund = fundamental
        f_mr = ma_price
        f_adapt = (
            ADAPTIVE_ALPHA * price + (1.0 - ADAPTIVE_ALPHA) * self.adaptive_forecast
            if self.adaptive_forecast is not None
            else price
        )
        f_opt = price * (1.0 + SENTIMENT_BIAS)
        f_pess = price * (1.0 - SENTIMENT_BIAS)
        f_noise = price * (1.0 + float(rng.normal(0.0, NOISE_SIGMA)))
        return np.array([f_trend, f_fund, f_mr, f_adapt, f_opt, f_pess, f_noise])

    def choose_and_predict(self, predictions: np.ndarray, rng: np.random.Generator,
                           temperature: float = 1.0) -> float:
        """按 fitness softmax 选一条规则, 返回其预测价."""
        z = self.fitness - self.fitness.max()  # 数值稳定
        probs = np.exp(z / max(temperature, 1e-9))
        probs /= probs.sum()
        idx = int(np.searchsorted(np.cumsum(probs), rng.random()))
        self.last_rule_used = min(idx, 6)
        self.adaptive_forecast = float(predictions[3])  # 更新 R4 状态
        return float(predictions[self.last_rule_used])

    def update_fitness(self, predictions: np.ndarray, old_price: float,
                       new_price: float, decay: float = 0.05) -> None:
        """虚拟盈亏制适应度更新 (B-H 标准).

        每条规则计分 = 若按其信号持仓的本子步虚拟收益:
            score_k = sign(pred_k − p_old) × r
        预测偏离当前价 ≠ 预测错 — 价格被系统性低估时, 基本面规则的买入信号
        会持续积累正 fitness 并主导市场 (价值发现). 全体旧 fitness 同步衰减;
        单条贡献截断 ±0.10 防单点爆炸.
        """
        self.fitness *= (1.0 - decay)
        if old_price <= 0 or new_price <= 0:
            return
        r = new_price / old_price - 1.0
        for k, pred in enumerate(predictions):
            direction = pred - old_price
            if abs(direction) < 1e-12:
                continue
            score = math.copysign(1.0, direction) * r
            self.fitness[k] += max(-0.10, min(0.10, score))


# ════════════════════════════════════════════════════════════
# 市场
# ════════════════════════════════════════════════════════════
@dataclass
class StockMarket:
    """聚合指数式股票市场 (全部分享同一价格序列).

    单位流的处理 (SFC 关键):
      本期净申购 Q_net (>0 买入): 家庭存款 ↓Q_net×p, 持仓 ↑Q_net
      本期净赎回 (<0 卖出): 反向. 存款在家庭间转移的部分对聚合无影响,
      因此只记净值 flows.
    """

    price: float = 10.0
    price_history: list[float] = field(default_factory=list)
    supply_units: float = 0.0              # 总股数 (企业发行总和)
    discount_rate: float = 0.05            # R2 基本面贴现率 (年化→月化使用)
    traders: list[Trader] = field(default_factory=list)

    # 参数 (from_config 注入)
    liquidity_lambda: float = 0.30         # 价格对超额需求敏感度
    depth: float = 100.0                   # 市场深度 (订单规模归一)
    cost_of_trading: float = 0.001         # 交易成本阈值
    order_fraction: float = 0.10           # 每次"净流入/流出"占家庭持仓或存款比例上限
    temperature: float = 1.0               # softmax 温度
    decay: float = 0.05                    # fitness 衰减
    substeps_per_month: int = 4            # 月内子步 (近似日级; 性能换频)

    @classmethod
    def from_config(cls, config, traders_n: int = 12) -> StockMarket:
        m = cls(
            liquidity_lambda=float(getattr(config, "stock_liquidity_lambda", 0.30)),
            depth=float(getattr(config, "stock_depth", 100.0)),
            cost_of_trading=float(getattr(config, "stock_cost_of_trading", 0.001)),
            order_fraction=float(getattr(config, "stock_order_fraction", 0.10)),
            temperature=float(getattr(config, "bh_temperature", 1.0)),
            decay=float(getattr(config, "bh_fitness_decay", 0.05)),
            substeps_per_month=int(getattr(config, "stock_substeps_per_month", 4)),
            discount_rate=float(getattr(config, "cb_neutral_rate", 0.02)) + 0.03,
        )
        m.traders = [Trader(id=f"trader_{i}") for i in range(traders_n)]
        return m

    # ── 基本信息 ──

    def fundamental(self, annual_dividend_per_share: float) -> float:
        """R2 基本面价 = 年股息 / 贴现率 (Gordon 无增长简化)."""
        if self.discount_rate <= 0:
            return self.price
        return max(annual_dividend_per_share, 0.0) / self.discount_rate

    def depth_scale(self) -> float:
        """fire-sale 冲击的规模分母 (约 2% 总供给为满格冲击)."""
        return max(self.supply_units * 0.02, 1.0)

    def _ma_price(self) -> float:
        window = MEAN_REV_WINDOW
        seg = self.price_history[-window:]
        return float(np.mean(seg)) if seg else self.price

    # ── 月度入口 ──

    def step_month(
        self,
        annual_dividend_per_share: float,
        rng: np.random.Generator,
        state=None,
    ) -> dict[str, float]:
        """跑一个月的子步循环; 返回 {net_flow_units, price_return}.

        净单位流 >0 = 家庭增持 (动用存款), <0 = 减持 (回流存款).
        """
        if self.supply_units <= 0 or not self.traders:
            return {"net_flow_units": 0.0, "price_return": 0.0}

        fund = self.fundamental(annual_dividend_per_share)
        start_price = self.price

        for _ in range(max(1, self.substeps_per_month)):
            prev = self.price_history[-1] if self.price_history else self.price
            ma = self._ma_price()
            p0 = self.price
            ed = 0.0
            all_preds: list[np.ndarray] = []
            for tr in self.traders:
                preds = tr.forecasts(
                    p0, prev, ma, fund, rng
                )
                all_preds.append(preds)
                expected = tr.choose_and_predict(preds, rng, self.temperature)
                edge = expected / max(p0, 1e-9) - 1.0
                size = self.order_fraction * min(abs(edge), 0.10) / 0.10
                if edge > self.cost_of_trading:
                    ed += size                       # 看涨买入 (单位流为正)
                elif edge < -self.cost_of_trading:
                    ed -= size                       # 看跌卖出

            excess = ed / self.depth
            new_price = max(p0 * (1.0 + self.liquidity_lambda * excess), 0.01)
            # 虚拟盈亏制 fitness: 所有规则按事后 P&L 计分 (价值发现通道,
            # 否则远离价格的基本面规则永远得不到正反馈, 市场无锚).
            for tr, preds in zip(self.traders, all_preds, strict=True):
                tr.update_fitness(preds, p0, new_price, self.decay)
            self.price = new_price


        ret = self.price / max(start_price, 1e-9) - 1.0
        self.price_history.append(self.price)
        return {
            "net_flow_units": 0.0,
            "price_return": ret,
            "fundamental": fund,
        }
