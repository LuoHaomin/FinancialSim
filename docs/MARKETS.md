# 市场层设计（Markets）

> 返回：[DESIGN.md](../DESIGN.md)
> 版本：v0.2 | 2026-08-27

---

## 4.1 商品市场（Goods Market）

**机制**：价格调整 + 库存缓冲（Walrasian-leaning）

```
需求：households 消费 + firms 投资 + 政府支出 + 出口
供给：firms 生产
价格调整：
  inventory > threshold → 降价 + 减产
  inventory < threshold → 提价 + 增产
价格粘性：调价频率有上限（卡尔沃定价）
```

### 关键参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| 价格调整速度 | 0.1/月 | 避免过度反应 |
| 库存目标 | 1 个月销量 | 缓冲需求波动 |
| 调价区间 | 6 个月 | 卡尔沃参数 θ ≈ 0.83 |

---

## 4.2 劳动市场（Labor Market）

**机制**：凯恩斯风格 — 工资粘性 + 配给

```
名义工资：每年/每半年重定一次
失业率 = (劳动力供给 - 劳动力需求) / 供给
求职：失业者按 job_search_intensity 寻找
雇佣：企业按预期需求 + 工资 + 工人匹配度
```

### 4.2.1 工资议价方程（修正版）

```python
def wage_setting(sector: str, state: 'SimulationState') -> float:
    """
    工资 = 通胀指数化 × 失业反馈 × 期望通胀
    核心: Taylor 风格工资合同 + 菲利普斯曲线
    """
    # ─── 1. 通胀指数化 (既定合同) ───
    backward_indexation = 0.7  # 70% 指数化（新凯恩斯典型值）
    w_indexed = state.last_wage[sector] * (
        1 + backward_indexation * state.inflation_yoy
    )

    # ─── 2. 失业反馈 (菲利普斯曲线, 连续化) ───
    # 失业缺口 = (NAIRU - 实际失业率) / NAIRU
    # > 0 → 劳动力市场紧 → 工资上行
    # < 0 → 劳动力市场松 → 工资下行（但粘性）
    unemployment_gap = (
        (state.nairu - state.unemployment_rate[sector]) / state.nairu
    )
    if unemployment_gap > 0:
        wage_pressure = 0.5 * unemployment_gap   # 上行：敏感
    else:
        wage_pressure = 0.2 * unemployment_gap   # 下行：粘性

    # ─── 3. 期望通胀 (前瞻) ───
    expected_pi = state.expected_inflation[sector]

    # ─── 4. 议价能力 (连续化) ───
    # 紧市场 → 工人议价强
    tightness = max(0, unemployment_gap)
    # 利润空间低 → 企业抵抗加薪能力弱
    profit_squeeze = max(0, 1 - state.firms.avg_profit_margin[sector] / HISTORIC_MARGIN)
    # 工会强度
    union = state.union_strength[sector]

    bargaining_power = 0.4 * tightness + 0.3 * profit_squeeze + 0.3 * union
    # 范围 [0, 1]

    # ─── 5. 最终工资（单项合成，无双重计价）───
    w_new = w_indexed * (
        1 + wage_pressure + 0.1 * bargaining_power + 0.3 * expected_pi
    )

    return max(w_new, MIN_WAGE)  # 最低工资保护
```

**v0.1 → v0.2 修正**：
- ❌ 旧版 `unemployment_rate < nairu` 返回 bool（0/1）→ ✅ 改为连续化缺口
- ❌ 旧版 `(1 - profit_margin)` 语义错误（margin=5% 得 0.95）→ ✅ 改为相对历史均值的偏离
- ❌ 旧版 `bargaining_power` 既乘 `wage_pressure` 又单独乘 `w_new`（双重计价）→ ✅ 合并为单项

### 4.2.2 工资粘性的实现

- **频率**：每年/每半年重定（粘性）
- **冲击传导**：通胀冲击 → 6-12 个月后工资反应
- **粘性是滞胀的关键**：油价冲击 → 通胀 → 但工资因合同未到期不变 → 实际工资下降 → 消费进一步收缩

### 4.2.3 关键涌现现象

| 现象 | 机制 |
|---|---|
| 结构性失业常态 | 不需要外部冲击，NAIRU > 0 |
| 疤痕效应 | `unemployment_duration ↑ → reemployment_wage ↓` |
| K 型复苏 | 部门间失业率差异 |
| 工资-物价螺旋 | 能源冲击 → 工资指数化 → 通胀 → 工资 ↑ → 通胀 ↑ |

---

## 4.3 信贷市场（Credit Market）

**机制**：Stiglitz-Weiss 信贷配给

```
贷款评估 = f(现金流, 抵押品, 杠杆率, 信用记录)
利率 ≠ 价格出清机制 → 而是筛选机制
存在"信贷配给均衡"：部分借款人即使愿意付更高利率也被拒
```

### 关键参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| LTV 上限 | 80% | 房贷最大贷款价值比 |
| DTI 上限 | 45% | 债务收入比上限 |
| 风险权重 | 按资产类别 | Basel II 标准权重 |
| 资本充足率要求 | 8% | Basel III 最低要求 |

### 信贷配给的数学表达

```python
def credit_rationing(bank, borrower, state):
    """
    Stiglitz-Weiss 信贷配给:
    银行不是简单按利率出清，而是按风险筛选
    """
    score = lending_score(bank, borrower, state)

    if score < MIN_SCORE:
        return None  # 拒贷（即使借款人愿付更高利率）

    # 通过筛选的借款人获得贷款
    loan_amount = min(
        borrower.loan_demand,
        borrower.collateral * state.policy.ltv_max,
        borrower.income * (1 / state.policy.dti_max - borrower.existing_dti),
        bank.available_lending_capacity(borrower)
    )

    rate = bank.loan_rate_for(borrower)  # 见 AGENTS.md Section 3.4.2
    return Loan(amount=loan_amount, rate=rate)
```

---

## 4.4 资产市场（Asset Markets）

⚠️ **不同资产类别用不同的预期机制——不能用同一套规则套所有资产。**

| 资产 | 机制 | 频率 | 异质性强度 |
|---|---|---|---|
| 股票 | Brock-Hommes（7 规则） | 日级 | 高 |
| 房产 | 租金锚定 + 抵押品渠道 | 月级 | 中 |
| 债券 | 期限结构 | 月级 | 低 |
| 外汇 | UIP（预留桩） | — | — |

### 4.4.1 股票市场（Stock Market）

**机制**：Brock-Hommes 异质信念（详见 [EXPECTATIONS.md](EXPECTATIONS.md)）

```
参与者: households + investment_banks + asset_funds
信念规则: 多种预测器共存，按过去表现调整权重
价格形成: 日级高频
流动性: 高（depth × 100）
```

#### 价格形成（简化做市商模型）

```python
def stock_price_formation(state):
    """
    做市商汇总所有参与者订单，出清价格
    """
    # 1. 收集所有参与者基于信念的订单
    for trader in state.stock_traders:
        belief = trader.choose_belief()  # Brock-Hommes
        expected_price = belief.forecast()
        if expected_price > state.stock_price * (1 + trader.cost_of_trading):
            trader.submit_buy(order_size=...)
        else:
            trader.submit_sell(order_size=...)

    # 2. 汇总供需
    total_demand = sum(buy_orders)
    total_supply = sum(sell_orders)

    # 3. 价格调整（做市商出清）
    excess_demand = (total_demand - total_supply) / total_supply
    price_change = LIQUIDITY_PARAM * excess_demand + noise
    state.stock_price *= (1 + price_change)

    # 4. 更新信念 fitness
    for trader in state.stock_traders:
        trader.update_fitness(actual_return=...)
```

### 4.4.2 房产市场（Housing Market）

⚠️ **房产不能用 Brock-Hommes**——因为：
1. 交易不连续（搜寻 + 成交周期数月）
2. 估值锚定在租金（现金流贴现）
3. 价格粘性大（无日内高频）
4. 抵押品渠道才是核心驱动

```python
class HousingMarket:
    """房产市场: 独立的低频机制"""

    def step(self, state):
        # ─── 1. 估值锚定 (现金流量折现) ───
        fundamental_price = (
            state.rent_index * state.rent_price_ratio_steady
        )

        # ─── 2. 抵押品渠道 (主驱动) ─── 🆕 修正
        # 可贷额度 = 抵押品价值 × LTV 比率
        # LTV 高 → 可贷多 → 需求强 → 价格涨
        collateral_capacity = (
            state.households.total_collateral * state.policy.ltv_max
        )

        # ─── 3. 供需平衡 (低频) ───
        demand = state.households.housing_demand(collateral_capacity)
        supply = state.firms.new_construction() + state.households.selling_inventory()

        # ─── 4. 价格调整 (慢) ───
        if supply > 0:
            price_gap = (demand - supply) / supply
            new_price = state.housing_price * (1 + 0.05 * price_gap)

        # ─── 5. 异质预期 (简化, 非 Brock-Hommes) ───
        expected_price = (
            0.4 * state.housing_price
          + 0.4 * fundamental_price
          + 0.2 * state.housing_price * (1 + trend_signal)
        )

        state.housing_price = new_price
```

**v0.1 → v0.2 修正**：
- ❌ 旧版 `collateral * (1 - ltv_max)`：LTV=0.8 时得 0.2× → 反了
- ✅ 新版 `collateral * ltv_max`：LTV=0.8 时得 0.8× → 宽松时抵押品容量更大

**关键参数**：

| 参数 | 值 | 说明 |
|---|---|---|
| 调整频率 | 月度 | 不是日级 |
| 流动性折扣 | 30% | 强制卖出 vs 正常交易 |
| 市场深度 | 5% | 紧急抛售价格冲击 |
| 租金/房价稳态比 | 15-20x | 大都市典型值 |

### 4.4.3 债券市场（Bond Market）

```python
class BondMarket:
    """债券市场: 利率期限结构"""

    def step(self):
        # 短期利率 = 政策利率
        short_rate = state.cb.policy_rate

        # 期限溢价（Nelson-Siegel 简化版）
        term_premium = (
            0.01  # 基础期限溢价 1%
          + 0.005 * (10 - maturity) / 10  # 长期溢价更高
        )

        # 期望未来短期利率
        expected_future_short = state.expected_policy_path

        # 长期利率 = 期望短期 + 期限溢价
        long_rate = expected_future_short + term_premium

        state.bond_yield = long_rate
```

**不使用 Brock-Hommes**——债券市场参与者更接近理性预期（机构为主）。

### 4.4.4 外汇市场（FX Market，预留桩）

```python
class FXMarket:
    """外汇市场: UIP + 套利 (MVP 不实现, 但架构预留)"""
    def step(self):
        # MVP: 固定汇率, 不执行
        state.fx_rate = state.fx_rate
        pass
```

**MVP 行为**：`FXMarket` 存在但不执行。Agent 状态中保留 `fx_position` 字段（默认 0）。

---

## 4.5 价格指数（Macro Price Indices）

### 4.5.1 CPI（消费者价格指数）

```python
CPI_WEIGHTS = {
    'consumer_goods': 0.30,    # 食品、服装、日用品
    'services':       0.30,    # 餐饮、医疗、教育
    'housing':        0.20,    # 虚拟租金 (imputed rent)
    'energy':         0.10,    # 燃油、电力
    'food':           0.05,    # 单独列出（政策关注）
    'other':          0.05,
}

def compute_cpi(state) -> float:
    cpi = 0
    for good, weight in CPI_WEIGHTS.items():
        cpi += weight * state.price_index[good]
    return cpi

inflation_yoy = (CPI_t / CPI_t_12 - 1) * 100
inflation_mom = (CPI_t / CPI_t_1 - 1) * 100  # 月环比, 年化
inflation_core = CPI 剔除 food + energy  # 核心通胀
```

### 4.5.2 资产价格指数（不进 CPI）

- 股价、房价**不进 CPI**（避免反馈循环）
- 但影响**财富**与**消费**（财富效应通道）

### 4.5.3 GDP 平减指数

```python
gdp_deflator = Nominal_GDP / Real_GDP
# 比 CPI 范围更广, 包括投资品、政府支出
```

---

## 4.6 通胀预期机制 🆕

⚠️ **通胀预期是工资设定、价格设定、资产定价的共同输入。没有它，货币政策传导断裂。**

### 4.6.1 按主体类型的预期形成

```python
def form_inflation_expectations(state: 'SimulationState'):
    """
    通胀预期: 按主体类型异质
    - Firms: 基于投入品价格（向后看）
    - Households: 基于 CPI 体验（向后看, 更慢）
    - Central Bank: 基于模型预测（部分前瞻）
    """
    # ─── 企业预期（投入品价格驱动）───
    for sector in state.sectors:
        # 企业关注自己部门的投入品价格变化
        input_cost_inflation = state.input_price_index[sector].pct_change(6)
        state.firm_expected_inflation[sector] = (
            0.6 * input_cost_inflation
          + 0.3 * state.inflation_yoy_lag_3
          + 0.1 * state.cb.target_inflation
        )

    # ─── 家庭预期（CPI 体验驱动，更慢）───
    state.hh_expected_inflation = (
        0.5 * state.inflation_yoy_lag_12  # 过去 12 个月
      + 0.3 * state.inflation_yoy_lag_6   # 过去 6 个月
      + 0.2 * state.cb.target_inflation   # 锚定
    )

    # ─── 央行预期（模型预测）───
    state.cb_expected_inflation = (
        0.3 * state.inflation_yoy
      + 0.3 * output_gap_inflation_pression  # 产出缺口隐含的通胀压力
      + 0.4 * state.cb.target_inflation       # 强锚定
    )
```

### 4.6.2 预期的教学意义

| 预期类型 | 行为 | 教学场景 |
|---|---|---|
| 适应性预期（家庭） | 缓慢调整 → 政策有滞后效果 | 沃尔克反通胀的代价 |
| 输入品驱动（企业） | 成本推动 → 工资-物价螺旋 | 1970s 滞胀 |
| 模型预测（央行） | 前瞻指引有效 | 现代货币政策 |

### 4.6.3 预期脱锚 🆕

```python
def check_expectation_anchoring(state):
    """
    当实际通胀持续偏离目标, 预期可能脱锚
    脱锚后: 即使通胀下降, 预期仍高 → 工资不降 → 通胀粘性
    """
    anchoring_deviation = abs(state.hh_expected_inflation - state.cb.target_inflation)
    if anchoring_deviation > 0.02:  # 偏离 2 个百分点以上
        # 家庭预期开始脱锚, 更多依赖近期通胀而非央行目标
        state.expectation_anchor_weight -= 0.01  # 逐渐降低对央行的信任
        state.expectation_anchor_weight = max(state.expectation_anchor_weight, 0.05)
```
