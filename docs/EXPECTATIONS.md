# 预期与学习机制

> 返回：[DESIGN.md](../DESIGN.md)
> 版本：v0.2 | 2026-08-27

---

## 9.0 设计原则

⚠️ **不同资产类别用不同的预期机制——不能用同一套规则套所有资产。**

| 资产类别 | 机制 | 复杂度 | 参与者 | 阶段 |
|---|---|---|---|---|
| 股票 | Brock-Hommes (7 规则) | 高 | 散户 + 投行 + 资管 | Phase 1 |
| 房产 | 租金锚定 + 抵押品 | 中 | 个体 + 开发商 | Phase 2 |
| 债券 | 期限结构 | 低 | CB + 银行 + 资管 | Phase 1 |
| 外汇 | UIP | 低 | — | Phase 3 |
| 通胀 | 适应性 + 锚定 | 中 | 所有主体 | Phase 1 |

**关键设计原则**：
- 不强制每类资产都"涌现"——债券接近理性、房产弱异质、股票强异质
- 异质性强度应该匹配**真实市场参与者结构**
- 通胀预期是所有主体的共同输入（见 MARKETS.md Section 4.6）

---

## 9.1 股票市场预期（Brock-Hommes 异质信念）

**核心思想**：市场参与者使用**多种预测规则**，根据**过去表现**动态切换。

### 9.1.1 信念规则集

每个资产市场参与者拥有 N 个信念规则：

| # | 规则 | 公式 | 适用情形 |
|---|---|---|---|
| R1 | **Trend Following** | `f = p[t-1] + 0.5·(p[t-1] - p[t-2])` | 趋势市 |
| R2 | **Fundamental** | `f = dividend / discount_rate` | 基本面定价 |
| R3 | **Mean Reverting** | `f = MA(p, window=20)` | 震荡市 |
| R4 | **Adaptive** | `f = α·p[t-1] + (1-α)·forecast[t-1]` | 一般情形 |
| R5 | **Optimistic** | `f = p[t-1]·(1 + bias)` | 牛市情绪 |
| R6 | **Pessimistic** | `f = p[t-1]·(1 - bias)` | 熊市情绪 |
| R7 | **Noise** | `f = p[t-1] + ε` | 随机游走 |

### 9.1.2 适应学习

```python
DECAY = 0.05  # 旧 fitness 衰减率


class Trader:
    """Brock-Hommes 交易者"""
    beliefs: list[BeliefRule]
    fitness: dict[int, float]  # rule_id → 适应度

    def choose_belief(self) -> BeliefRule:
        """按 fitness 的 softmax 概率选择信念"""
        z = np.array([self.fitness[id(b)] for b in self.beliefs])
        # softmax 温度控制选择集中度
        temperature = 1.0
        probs = np.exp(z / temperature)
        probs /= probs.sum()
        return np.random.choice(self.beliefs, p=probs)

    def update_fitness(self, belief_used: BeliefRule, actual_price: float):
        """
        更新所有信念的 fitness
        - 所有信念的旧 fitness 衰减
        - 只有被使用的信念根据预测误差更新
        """
        bid = id(belief_used)
        forecast = belief_used.forecast()

        # 预测误差（负值 = 预测准确）
        error = -abs(forecast - actual_price) / actual_price

        # 衰减所有旧 fitness
        for b in self.beliefs:
            self.fitness[id(b)] *= (1 - DECAY)

        # 更新被使用信念的 fitness
        self.fitness[bid] += error

    def generate_order(self, state) -> Order:
        """基于所选信念生成交易指令"""
        belief = self.choose_belief()
        expected = belief.forecast()
        current = state.stock_price

        if expected > current * (1 + self.cost_of_trading):
            # 看涨 → 买入
            share = min(self.cash * 0.3, self.risk_budget) / current
            return Order('buy', share)
        else:
            # 看跌 → 卖出
            share = self.stocks * 0.3
            return Order('sell', share)
```

### 9.1.3 涌现的金融现象

这些现象是 Brock-Hommes 的**内生结论**，不需要额外假设：

| 现象 | 机制 | 验证 |
|---|---|---|
| 股价厚尾 | 异质信念切换导致大幅波动 | kurtosis > 3 |
| 波动聚集 | 市场从分散 → 一致 → 再次分散 | |r_t| autocorr > 0.1 |
| 泡沫与崩盘 | 趋势跟风者占主导 → 价格偏离基本面 | 内生涌现 |
| 交易量-波动相关性 | 信念分歧大 → 交易活跃 → 波动大 | corr(vol, volume) > 0 |

### 9.1.4 泡沫的内生路径

```
阶段 1: 基本面稳定
  多种信念均匀分布, 价格贴近基本面

阶段 2: 趋势显现
  某些趋势跟风者连续获利 → fitness 上升 → 占比增加
  → 买入压力 → 价格上涨 → 进一步验证趋势策略
  → 自我强化循环

阶段 3: 泡沫
  趋势跟风者占比 > 50%
  基本面交易者的 fitness 相对下降, 但仍存在
  价格严重偏离基本面

阶段 4: 崩盘
  价格过高 → 任何坏消息 → 趋势反转
  → 趋势跟风者 fitness 急降
  → 卖出压力 → 价格下跌 → 恐慌性卖出
  → 甩卖螺旋（叠加银行 Fire-Sale）
```

---

## 9.2 房产市场预期（租金锚定 + 抵押品渠道）

**房产不能用 Brock-Hommes**——理由见 MARKETS.md Section 4.4.2。

```python
class HousingExpectation:
    """房产预期: 简化, 异质性较弱"""

    def expected_price(self, household, state) -> float:
        # 锚定基本面
        fundamental = state.rent_index * state.rent_price_ratio_steady

        # 近期趋势 (弱化)
        trend = state.housing_price * (1 + 0.1 * state.price_momentum)

        # 抵押品预期 (宽松政策 → 涨)
        collateral_signal = (
            0.3 if state.policy.ltv_max > 0.8
            else -0.2 if state.policy.ltv_max < 0.6
            else 0
        )

        # 异质性: 家庭对未来收入信心不同
        income_confidence = (
            0.5 * (1 + 0.2 * (household.wage / state.avg_wage - 1))
        )

        # 加权
        return (
            0.45 * fundamental
          + 0.25 * trend
          + 0.15 * state.housing_price * (1 + collateral_signal)
          + 0.15 * income_confidence * state.housing_price
        )
```

**异质性来源**：
- 家庭对未来抵押品可得性的预期（基于货币政策）
- 家庭对未来收入的信心
- 但**不**使用 7 条信念规则的复杂机制

---

## 9.3 债券市场预期（期限结构）

```python
class BondExpectation:
    """债券: 基于期限结构的理性预期
    不使用 Brock-Hommes —— 债券市场参与者更接近理性（机构为主）
    """

    def expected_long_rate(self, state) -> float:
        # 期望未来短期利率（基于 CB 指引 + 市场判断）
        expected_short = state.cb.expected_policy_path

        # 期限溢价（Nelson-Siegel 简化版）
        # 长期限 → 更高溢价
        term_premium = 0.01 + 0.005 * state.maturity / 10

        return expected_short + term_premium
```

---

## 9.4 外汇市场预期（UIP）

⚠️ Phase 3 实现。架构预留：

```python
class FXExpectation:
    """外汇: 非抛补利率平价 (UIP)
    E[e_{t+1}] = e_t · (1 + r_dom) / (1 + r_foreign)
    后续: carry trade, 套利交易
    """
    pass
```
