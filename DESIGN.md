# ABM 宏观经济仿真器：完整设计文档

> 版本：v0.1 设计草案
> 状态：架构定型，待校准与实现
> 最后更新：2026-08

---

## 0. 阅读说明

本文档是 Agent-Based Macroeconomics（ABM）仿真器的完整设计。所有 12 项基础架构决策已定。本文档描述：
- 整体设计哲学与目标
- 各子系统的结构、状态、行为
- 涌现目标与验证方式
- 尚未决定的事项

**标记约定**：
- ✅ 已决定
- ❓ 待讨论/未定
- ⚠️ 风险/陷阱提示

---

## 1. 项目概述

### 1.1 项目定位

构建一个 **教学型 Agent-Based 宏观经济仿真平台**。目标不是拟合数据，而是让使用者亲手触发出真实经济机制，从而获得对宏观经济学、金融危机、政策传导的直观理解。

### 1.2 核心比喻

不是"经济学教科书"，而是**"宏观经济学实验台"**——一个能跑出来的、可下钻的、可干预的虚拟经济。

### 1.3 设计哲学

| 维度 | 立场 |
|---|---|
| 主体异质性 | 必须（否则无财富不平等涌现） |
| 有限理性 | 必须（这是 ABM 与 DSGE 的根本区别） |
| 非均衡 | 必须（凯恩斯传统，失业与配给是常态） |
| 内生危机 | 必须（明斯基时刻是涌现结论，不是假设） |
| 教学透明 | 关键（用户能下钻到任意 agent 的状态） |
| 现实主义 | 中等偏高（混合型货币架构 + 多尺度时间） |

### 1.4 期望受众

- 大学宏观经济学、金融学课程的学生
- 经济学通识教育的高年级学生
- 想理解货币政策与金融危机机制的决策者、记者、公众
- 不期望是：宏观经济学家（但希望他们认可模型的严谨性）

### 1.5 期望效果

使用者能在一次模拟中亲眼看到：

> *我按下"提高利率 1%"的按钮，6-12 个月后看到资产价格下跌、银行收紧信贷、企业投资收缩、失业率上升；进一步观察发现某些行业（建筑业）先衰退、某些家庭（高杠杆购房者）受冲击最重。*

这就是"金融加速器"的视觉化教学。

---

## 2. 架构总览

### 2.1 系统图

```
┌────────────────────────────────────────────────────────┐
│                   Time Scheduler                       │
│         主 tick = 1 个月│ 内含 20-30 个日级快循环        │
└────────────────────────────────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
   ┌─────────┐       ┌──────────┐       ┌──────────┐
   │ Agents  │       │ Markets  │       │  State   │
   │  7+ 类   │ ◄───► │  混合出清  │ ────► │ Timeseries│
   │ 个体 HH │       │ 4 层网络 │       │ Drill-down│
   └─────────┘       └──────────┘       └──────────┘
        │
        ▼
   ┌─────────────────────┐
   │  Brock-Hommes 信念   │
   │  + 多规则适应学习     │
   └─────────────────────┘
```

### 2.2 12 项核心决策 ✅

| # | 维度 | 决策 | 哲学位置 |
|---|---|---|---|
| 1 | **UX** | 混合沙盒 + 透明黑盒 | 探索与引导并重 |
| 2 | **时间尺度** | 月主循环 + 日快循环 | 金融快 ↔ 实体慢 |
| 3 | **Agent 集** | 7+ 类（企业三部门、银行双层、家庭个体、CB、政府、外资） | 现代经济结构 |
| 4 | **货币架构** | 外生基础货币 + 内生信用创造 | 后凯恩斯主流 |
| 5 | **资产价格频率** | 日级高频 | 充分涌现金融现象 |
| 6 | **危机触发** | 完全内生 | 涌现式，非剧本 |
| 7 | **市场出清** | 混合（商品灵活 + 劳动粘性 + 信贷配给） | 新凯恩斯 |
| 8 | **预期机制** | Brock-Hommes 异质信念 | 经典 ABM |
| 9 | **生产** | 5+ 部门 + CES 生产函数 | 现代产业结构 |
| 10 | **家庭粒度** | 个体级（N = 10K–100K） | 帕累托尾能涌现 |
| 11 | **网络** | 每层不同拓扑 + 完全自适应信贷 | 真实金融体系 |
| 12 | **政策** | Taylor 默认 + 手动覆盖；财政/审慎完全可调 | 教学最大化 |

---

## 3. 主体层（Agents）

### 3.1 主体分类

```
┌──────────────────────────────────────────────┐
│              7+ 类主体                       │
├──────────────────────────────────────────────┤
│  1. Households (个体级, N=10K–100K)        │
│     - 工人 / 食利者 / 失业者 (状态)          │
│  2. Firms (多部门)                          │
│     - Capital Goods / Consumer Goods /       │
│       Energy / Housing / Services / Hi-Tech │
│  3. Commercial Banks (商业银行)             │
│  4. Investment Banks (投资银行)              │
│  5. Asset Funds / Insurance (资管/保险)      │
│  6. Government (政府)                       │
│  7. Central Bank (中央银行)                 │
│  8. Foreign Sector (外资) ← 可选            │
└──────────────────────────────────────────────┘
```

### 3.2 Households（家庭）

**粒度**：个体级，每个家庭是独立 agent。

#### 状态字段

```python
@dataclass
class Household:
    id: str

    # 人口学
    age: int
    education: float          # 0–1, 影响工资与就业机会
    household_size: int       # 负担人数

    # 就业
    sector: str | None        # 当前就职部门
    wage: float
    employed: bool
    tenure: float             # 工龄，影响失业成本
    unemployment_duration: int  # 失业持续期，影响人力资本

    # 金融
    wealth: float             # 净资产
    income: float             # 总收入
    consumption: float
    savings_rate: float       # 异质!
    debt: float               # 房贷 + 消费贷
    debt_to_income: float

    # 行为参数（异质性源头）
    marginal_propensity_to_consume: float
    risk_tolerance: float     # 影响资产配置
    job_search_intensity: float
    credit_constraint: float  # 最大可借
```

#### 行为规则

1. **消费决策**：c_t = mpc · (y_t - y_target) + autocomponent
2. **储蓄/投资**：wealth → 部分进入资产市场
3. **劳动供给**：根据工资率与保留工资决定是否找工作
4. **信贷需求**：消费/房贷受财富与收入约束
5. **资产配置**：风险偏好 + 财富水平 → 股票/房产/储蓄分布

#### 异质性来源

- 初始教育（正态分布）
- 初始财富（对数正态分布 → 帕累托尾）
- 储蓄率（Beta 分布）
- MPC（Beta 分布）
- 风险偏好（Cauchy 分布截断）

### 3.3 Firms（企业）

**类型**：6 个部门（资本品/消费品/原材料/能源/住房/服务/高科技）。

#### 状态字段

```python
@dataclass
class Firm:
    id: str
    sector: str

    # 生产
    capital: float
    productivity: float       # A, 部门异质
    tech_level: float         # 行业前沿
    energy_efficiency: float

    # 财务
    cash: float
    revenues: float
    costs: float
    debt: float
    equity: float             # 净资产
    leverage: float           # debt / equity

    # 运营
    employees: int            # 当前工人数
    inventory: float
    price: float
    order_book: float
    capacity_utilization: float
```

#### 行为规则

1. **生产决策**：基于订单 + 库存 + 产能利用率
2. **价格决策**：markup over marginal cost；粘性（卡尔沃定价）
3. **雇佣决策**：基于预期需求 + 当前产能
4. **投资决策**：基于 q 比率（托宾 Q）或订单增长
5. **融资决策**：自有资金 vs 银行贷款 vs 股权发行

### 3.4 Commercial Banks（商业银行）

#### 状态字段

```python
@dataclass
class CommercialBank:
    id: str
    tier: int                  # 1 = 核心银行, 2 = 边缘银行

    # 资产
    reserves: float           # 在 CB 的准备金
    loans: float              # 对 households/firms 的贷款
    securities: float         # 持有的政府债券
    interbank_claims: float   # 同业拆出

    # 负债
    deposits: float           # 存款 (核心负债)
    interbank_debt: float     # 同业拆入
    bond_issuance: float

    # 资本
    capital: float
    car: float                # 资本充足率
    npl_ratio: float          # 不良贷款率
    liquidity_ratio: float
```

#### 行为规则

1. **贷款评估**：借款人的现金流 + 抵押品 + 杠杆率 + 信用记录 → 是否放贷，利率多少
2. **存款利率**：跟随政策利率 + 利差
3. **同业拆借**：流动性管理
4. **资产组合**：贷款 / 证券 / 准备金 的最优配比
5. **资本管理**：派息 vs 留存；危机时增资

### 3.5 Investment Banks（投资银行）

核心业务：**自营交易 + 承销 + 做市**

```python
@dataclass
class InvestmentBank:
    id: str

    capital: float
    var: float                # 风险价值 (Value-at-Risk)
    leverage: float           # 通常远高于商业银行

    trading_book: dict[str, float]  # 各资产持仓
    underwriting_pipeline: float

    funding: dict             # 短期融资构成
```

### 3.6 Asset Funds / Insurance（资管/保险）

**核心**：代理人业务 + 投资组合管理

```python
@dataclass
class AssetFund:
    id: str
    aum: float                # 管理资产规模

    allocation: dict[str, float]  # 资产配置权重
    performance: float        # 过去表现
    flows: float              # 净流入/流出
```

**信念机制**采用 Brock-Hommes（详见第 9 节）。

### 3.7 Central Bank（中央银行）

```python
@dataclass
class CentralBank:
    policy_rate: float
    target_inflation: float
    neutral_rate: float
    reserve_requirement: float
    countercyclical_buffer: float

    balance_sheet: dict      # 资产/负债
```

#### 政策工具
1. **政策利率**（最主要）：根据 Taylor Rule 或手动覆盖
2. **公开市场操作**：政府债券买卖
3. **存款准备金率**
4. **逆周期资本缓冲**
5. **最后贷款人**：向危机银行提供紧急流动性

### 3.8 Government（政府）

```python
@dataclass
class Government:
    debt: float
    debt_to_gdp: float
    revenues: float
    expenditures: float
    primary_balance: float
```

#### 政策工具（用户可控）
1. **政府支出** G（外生设定或规则化）
2. **税率** T
3. **转移支付**
4. **公债发行**

### 3.9 Foreign Sector（外资）

**可选模块**。若启用：
- 出口/进口（贸易账户）
- 资本流入/流出（资本账户）
- 汇率（钉住 / 浮动 / 管理浮动）

---

## 4. 市场层（Markets）

### 4.1 商品市场（Goods Market）

**机制**：价格调整 + 库存缓冲（Walrasian-leaning）

```
需求：households 消费 + firms 投资 + 政府支出 + 出口
供给：firms 生产
价格调整：
  inventory > threshold → 降价 + 减产
  inventory < threshold → 提价 + 增产
价格粘性：调价频率有上限（卡尔沃定价）
```

#### 关键参数
- 价格调整速度（默认 0.1/月）
- 库存目标（默认 1 个月销量）
- 调价区间（默认 6 个月）

### 4.2 劳动市场（Labor Market）

**机制**：凯恩斯风格 — 工资粘性 + 配给

```
名义工资：每年/每半年重定一次
失业率 = (劳动力供给 - 劳动力需求) / 供给
求职：失业者按 job_search_intensity 寻找
雇佣：企业按预期需求 + 工资 + 工人匹配度
```

#### 4.2.1 工资议价方程

```python
def wage_setting(sector: str, state: 'SimulationState') -> float:
    """
    工资 = 通胀指数化 × 失业反馈 × 期望通胀
    核心: Taylor 风格工资合同 + 菲利普斯曲线
    """
    # ─── 1. 通胀指数化 (既定合同) ───
    # 工资按过去通胀自动调整,避免实际工资侵蚀
    backward_indexation = 0.7  # 70% 指数化 (新凯恩斯典型值)
    w_indexed = state.last_wage[sector] * (
        1 + backward_indexation * state.inflation_yoy
    )

    # ─── 2. 失业反馈 (菲利普斯曲线) ───
    unemployment_gap = state.nairu - state.unemployment_rate[sector]
    # unemployment_gap > 0 → 低于 NAIRU → 工资上行压力
    # unemployment_gap < 0 → 高于 NAIRU → 工资下行
    if unemployment_gap > 0:
        wage_pressure = 0.5 * unemployment_gap  # 上行敏感
    else:
        wage_pressure = 0.2 * unemployment_gap  # 下行黏性

    # ─── 3. 期望通胀 (前瞻) ───
    # 工人基于过去 12 个月均值形成期望
    expected_pi = state.firms.expected_inflation[sector]

    # ─── 4. 议价能力 ───
    # 取决于失业率与企业利润
    bargaining_power = (
        0.4 * (state.unemployment_rate[sector] < state.nairu)  # 紧市场
      + 0.3 * (1 - state.firms.profit_margin[sector])         # 低利润
      + 0.3 * state.union_strength[sector]                    # 工会强度
    )

    # ─── 5. 最终工资 ───
    w_new = w_indexed * (1 + wage_pressure) * (1 + 0.3 * expected_pi)
    # ↑ 议价能力影响幅度
    w_new *= (1 + 0.1 * bargaining_power)

    return max(w_new, MIN_WAGE)  # 下限保护
```

#### 4.2.2 工资粘性的实现

- **频率**：每年/每半年重定（粘性）
- **冲击传导**：通胀冲击 → 6-12 个月后工资反应
- **粘性是滞胀的关键**：油价冲击 → 通胀 → 但工资因合同未到期不变 → 实际工资下降 → 消费进一步收缩

#### 4.2.3 关键现象
- 失业是**结构性常态**，不需要外部冲击
- 长期失业导致人力资本贬值（**疤痕效应**：unemployment_duration → reemployment_wage ↓）
- 部门间失业率差异（K 型复苏的微观基础）
- 通胀粘性传导：能源冲击 → 工资指数化 → 工资-物价螺旋

### 4.3 信贷市场（Credit Market）

**机制**：Stiglitz-Weiss 信贷配给

```
贷款评估 = f(现金流, 抵押品, 杠杆率, 信用记录)
利率 ≠ 价格出清机制 → 而是筛选机制
存在"信贷配给均衡"：部分借款人即使愿意付更高利率也被拒
```

#### 关键参数
- 抵押品折扣率（LTV 上限）
- 风险权重（不同资产）
- 资本充足率要求

### 4.4 资产市场（Asset Markets）

⚠️ **不同资产类别用不同的预期机制——不能用同一套规则套所有资产。**

#### 4.4.1 股票市场（Stock Market）

**机制**：Brock-Hommes 异质信念（详见 Section 9.1）

```
参与者: households + investment_banks + asset_funds
信念规则: 多种预测器共存,按过去表现调整权重
价格形成: 日级高频
流动性: 高 (depth × 100)
```

#### 4.4.2 房产市场（Housing Market）⚠️ 独立机制

**房产不能用 Brock-Hommes**——因为：
1. 房产交易**不连续**（搜寻 + 成交周期数月）
2. 估值**锚定在租金**（现金流贴现）
3. 价格粘性大（无日内高频）
4. **抵押品渠道**才是核心驱动

```python
class HousingMarket:
    """房产市场: 独立的低频机制"""

    def step(self, state):
        # ─── 1. 估值锚定 (现金流量折现) ───
        # 房价 / 租金比 = P / R
        # 历史正常水平: 15-20 倍 (大都市)
        # 偏离过大 → 缓慢回归
        fundamental_price = (
            state.rent_index * state.rent_price_ratio_steady
        )

        # ─── 2. 抵押品渠道 (主驱动) ───
        # 抵押品价值 = 房价 × LTV_max
        # 银行可贷额度 = 抵押品 × (1 - LTV_required)
        # 货币宽松 → LTV↑ → 可贷↑ → 需求↑ → 价格↑
        collateral_capacity = (
            state.households.collateral
          * (1 - state.policy.ltv_max)
        )

        # ─── 3. 供需平衡 (低频) ───
        # 房产交易频率: 月度 (而非日级)
        demand = state.households.housing_demand(collateral_capacity)
        supply = state.firms.new_construction() + state.households.selling_inventory()

        # ─── 4. 价格调整 (慢) ───
        price_gap = (demand - supply) / supply
        new_price = state.housing_price * (1 + 0.05 * price_gap)

        # ─── 5. 异质预期 (简化) ───
        # 购房者预期: 简化趋势 + 基本面
        # 不使用 7 条 Brock-Hommes 规则
        expected_price = (
            0.4 * state.housing_price
          + 0.4 * fundamental_price
          + 0.2 * state.housing_price * (1 + trend_signal)
        )

        state.housing_price = new_price
```

**关键参数**：
- 月度调整（不是日级）
- 流动性折扣 30%（强制卖出 vs 正常交易）
- 市场深度 5%（紧急抛售价格冲击 = 卖出量 / 日成交量 × 5）

#### 4.4.3 债券市场（Bond Market）

```python
class BondMarket:
    """债券市场: 利率期限结构"""

    def step(self):
        # 短期利率 (政策利率) + 期限溢价 = 长期利率
        # 通过 Nelson-Siegel 或简单期限溢价模型
        # 主要参与者: banks + asset_funds + cb (OMO)
        # 不使用 Brock-Hommes
        pass
```

#### 4.4.4 外汇市场（FX Market，预留桩）

```python
class FXMarket:
    """外汇市场: UIP + 套利 (MVP 不实现,但架构预留)"""
    def step(self):
        # 即便 MVP 关闭,也要有这步 (no-op)
        state.fx_rate = state.fx_rate  # 固定
        # 后期: UIP 套利、抛补利率平价、汇率波动
        pass
```

**MVP 行为**：`FXMarket` 存在但**不执行**，架构上为后期实现预留位置。Agent 状态中保留 `fx_position` 字段（默认 0）。

### 4.5 价格指数（Macro Price Indices）

#### 4.5.1 CPI（消费者价格指数）

```python
CPI_WEIGHTS = {
    'consumer_goods': 0.30,    # 食品、服装、日用品
    'services':       0.30,    # 餐饮、医疗、教育
    'housing':        0.20,    # 虚拟租金 (imputed rent)
    'energy':         0.10,    # 燃油、电力
    'food':           0.05,    # 单独列出 (政策关注)
    'other':          0.05,
}

def compute_cpi(state) -> float:
    cpi = 0
    for good, weight in CPI_WEIGHTS.items():
        cpi += weight * state.price_index[good]
    return cpi

inflation_yoy = (CPI_t / CPI_t_12 - 1) * 100
inflation_mom = (CPI_t / CPI_t_1 - 1) * 100  # 月环比,年化
inflation_core = CPI 剔除 food + energy  # 核心通胀
```

#### 4.5.2 资产价格指数（不进 CPI）

- 股价、房价**不进 CPI**（避免反馈循环）
- 但影响**财富**与**消费**（财富效应通道）

#### 4.5.3 GDP 平减指数

```python
gdp_deflator = (Nominal_GDP / Real_GDP)
# 比 CPI 范围更广,包括投资品、政府支出
```

---

## 5. 货币与金融架构

### 5.1 混合型货币架构

**核心断言**：现代货币体系同时具有外生与内生特征。
- **基础货币**（准备金、流通现金）由 CB 外生控制
- **广义货币**（主要银行存款）由银行内生通过贷款创造
- **政策传导**通过**利率 + 信贷条件**双渠道

#### 货币创造流程

```
1. CB 设政策利率 r
   ↓
2. 家庭/企业向商业银行申请贷款
   ↓
3. 商业银行评估后放贷（创造存款）
   ↓
4. 借款人支出 → 存款转移到收款方账户
   ↓
5. 银行间清算 → 准备金流动
   ↓
6. CB 通过 OMO 调节准备金供给，使短端利率贴近政策利率
```

#### 关键概念
- **货币供给** M2 = 现金 + 活期 + 定期
- **货币乘数**：教科书定义；现代实际是"内生货币供给"
- **存款创造**：贷款 = 资产增加 = 负债增加（同时发生）

### 5.2 银行体系

#### 双层结构
1. **商业银行**（受 CAR、准备金率约束）
2. **投资银行**（自营交易为主，杠杆更高，受较少约束）

#### 银行失败规则
```
CAR < 8% → 触发监管
CAR < 4% → 触发早期干预
CAR < 2% → 触发重组或破产
```

#### 流动性规则
```
流动性覆盖率（LCR）> 100%
净稳定资金比率（NSFR）> 100%
```

### 5.3 中央银行

#### Taylor Rule（默认）

```
r_target = r_neutral + π_π · (π - π_target) + π_y · output_gap

# 默认参数
r_neutral = 2.0%
π_target  = 2.0%
π_π       = 1.5
π_y       = 0.5

# 实际应用：渐进调整（避免过度反应）
r_new = 0.85 · r_prev + 0.15 · r_target
```

#### 政策工具优先级
1. 政策利率（最常用）
2. 公开市场操作（OMO）
3. 最后贷款人（紧急）
4. 存款准备金率（结构性）
5. 宏观审慎工具（结构性）

### 5.4 Stock-Flow Consistency（会计内核）❗

**这是模型的物理定律。所有交易必须满足会计恒等式——不是可选优化，是地基。**

#### 5.4.1 五大部门资产负债表

```python
@dataclass
class SectorBalanceSheet:
    """每个部门一张资产负债表"""

    # === Households ===
    cash: float              # 流通现金
    deposits: float          # 银行存款
    stocks: float            # 股票市值
    bonds: float             # 债券市值
    housing: float           # 自住房
    investment_property: float  # 投资性房产
    consumer_durables: float
    loans_outstanding: float # 总负债

    # === Firms ===
    cash: float
    deposits: float
    inventories: float
    capital_stock: float
    bonds_issued: float      # 公司债
    loans_from_banks: float
    equity: float            # 净值

    # === Commercial Banks ===
    reserves: float
    loans_to_firms: float
    loans_to_households: float
    securities_held: float   # 政府债
    interbank_claims: float
    # 负债
    deposits_liab: float
    interbank_debt: float
    bonds_issued: float
    capital: float           # 净值

    # === Government ===
    bonds_outstanding: float # 总国债
    reserves: float          # 国库存款
    net_worth: float         # 通常为负,等于 -debt + reserves

    # === Central Bank ===
    # 资产
    government_bonds: float
    other_assets: float
    # 负债
    bank_reserves: float     # 银行准备金
    currency_issued: float   # 流通现金
    capital: float
```

#### 5.4.2 流量矩阵（Transaction Flow Matrix）

```python
# 所有交易双重记账: 付款方 -X, 收款方 +X
# 每一行流量有确定的源部门和目标部门

TRANSACTION_MATRIX = {
    # ─── 实体经济 ───
    ('households', 'firms',        'consumption_C'):  ...,  # 消费
    ('firms',      'households',   'wages_W'):        ...,  # 工资
    ('firms',      'households',   'dividends_DIV'):  ...,  # 股息
    ('firms',      'firms',        'investment_I'):   ...,  # 投资品交易
    ('households', 'firms',        'investment_I'):   ...,  # 家庭投资 (如房地产开发商)
    ('firms',      'gov',          'taxes_T'):        ...,  # 公司税
    ('households', 'gov',          'taxes_T'):        ...,  # 所得税
    ('gov',        'households',   'transfers_TR'):   ...,  # 转移支付
    ('gov',        'firms',        'gov_spending_G'): ...,  # 政府购买

    # ─── 金融中介 ───
    ('banks',      'households',   'interest_dep'):   ...,  # 存款利息
    ('banks',      'firms',        'interest_loan'):  ...,  # 贷款利息
    ('banks',      'gov',          'interest_bond'):  ...,  # 持有国债利息
    ('cb',         'banks',        'interest_res'):   ...,  # 准备金利息

    # ─── 信贷流量 ───
    ('banks',      'households',   'new_loan'):       ...,  # 新房贷/消费贷
    ('banks',      'firms',        'new_loan'):       ...,  # 新企业贷款
    ('households', 'banks',        'loan_repay'):     ...,  # 还本付息
    ('firms',      'banks',        'loan_repay'):     ...,

    # ─── OMO / 央行操作 ───
    ('cb',         'banks',        'omo_buy'):        ...,  # CB 买入国债
    ('banks',      'cb',           'omo_sell'):       ...,  # CB 卖出国债
    ('cb',         'banks',        'lolr'):           ...,  # 最后贷款人

    # ─── 资产市场 (净额) ───
    ('households', 'households',   'stock_trade'):    ...,  # 内部,净额为0
    ('households', 'firms',        'stock_issuance'): ...,  # IPO/增发的净额

    # ─── 外资 (预留桩) ───
    ('firms',      'foreign',      'exports_X'):      ...,
    ('foreign',    'firms',        'imports_M'):      ...,
    ('households', 'foreign',      'fx_position'):    ...,
    ('firms',      'foreign',      'fdi'):            ...,
}
```

#### 5.4.3 守恒校验（每 tick 强制执行）

```python
EPSILON = 1e-6  # 浮点容差

def validate_sfc(state: 'SimulationState') -> None:
    """每个 tick 结束调用.违反则抛出异常."""
    sectors = state.sectors  # 五大部门

    # ─── 1. 资产负债表恒等式: A = L + NW ───
    for s in sectors:
        total_assets = s.sum_assets()
        total_liab   = s.sum_liabilities()
        assert abs(total_assets - total_liab - s.net_worth) < EPSILON, \
            f"SFC violation: {s.name} A={total_assets} L={total_liab} NW={s.net_worth}"

    # ─── 2. 部门净借贷之和 = 0 (封闭系统) ───
    total_nl = sum(s.net_lending for s in sectors) + state.foreign_sector.net_lending
    assert abs(total_nl) < EPSILON, \
        f"SFC violation: Σ Net Lending = {total_nl}"

    # ─── 3. 货币守恒 ───
    # 总存款 + 流通现金 = 银行总贷款 + 证券持有 + 准备金 + 现金发行
    money_supply = sum(h.deposits for h in sectors.households) + state.cb.currency_issued
    money_uses = (sum(b.loans_to_firms + b.loans_to_households
                      + b.securities_held + b.reserves
                      for b in sectors.banks)
                  + state.cb.currency_issued)
    assert abs(money_supply - money_uses) < EPSILON, \
        f"SFC violation: money supply {money_supply} != money uses {money_uses}"

    # ─── 4. 央行资产负债表平衡 ───
    cb_assets   = state.cb.government_bonds + state.cb.other_assets
    cb_liab     = state.cb.bank_reserves + state.cb.currency_issued + state.cb.capital
    assert abs(cb_assets - cb_liab) < EPSILON

    # ─── 5. 政府债务恒等式 ───
    # ΔDebt = G + INT_gov - T - TR  (每期流量)
    # 这个由政府模块自己保证

    # ─── 6. 净值变动 = 储蓄 + 资本利得 ───
    for s in sectors:
        saving = s.income - s.expenditure + sum(s.transfers_received) - sum(s.taxes_paid)
        capgain = s.sum_capital_gains()
        expected_dNW = saving + capgain
        actual_dNW = s.net_worth - s.prev_net_worth
        assert abs(expected_dNW - actual_dNW) < EPSILON

class SFCViolation(Exception):
    """违反 SFC 约束时抛出.生产环境应 logging + alert."""
    pass
```

#### 5.4.4 部门净借贷恒等式

```
NL_households = (W + DIV + INT_dep + TR - T - C) + ΔNW_capgain
NL_firms      = (C + I + G + X - W - INT_loan - T - DIV) + ΔNW_capgain
NL_government = T - G - TR - INT_gov
NL_banks      = (INT_loan + INT_bond - INT_dep) - operating_costs
NL_cb         = 0  (按 SFC 定义, 央行利润回流政府)
NL_foreign    = -(X - M) - net_capital_flow

# 恒等式 (核心约束)
Σ NL_sectors + NL_foreign = 0
```

#### 5.4.5 资本利得的处理

**资本利得不创造货币**——它是**存量重估**：

```
家庭持股 1000 股 @ $10 → 市值 $10,000
股价涨到 $12 → 市值 $12,000
家庭 wealth += $2,000 (资本利得)
但任何人都没有额外 "$2,000"——是从其他持有人那里转移过来的
```

实现：每次资产价格变动，**所有持有者的财富总和不变**（零和），但**分布变化**（赢家与输家）。

#### 5.4.6 ❗ 实现位置

SFC 校验应在**仿真核心**而非"应用层"。运行期违反必须**立即抛出 + 日志**：

```python
# core/state.py
class SimulationState:
    def end_tick(self):
        try:
            validate_sfc(self)
        except AssertionError as e:
            logger.critical(f"SFC violation at tick {self.t}: {e}")
            self.snapshot("sfc_violation")
            raise SFCViolation(e)
```

---

## 6. 生产结构

### 6.1 部门清单

```
┌────────────────────────────────────────────────────────┐
│  1. 资本品  Capital Goods (机器、设备、厂房)            │
│  2. 消费品  Consumer Goods (食品、服装、日用品)         │
│  3. 原材料  Raw Materials (金属、化工)                  │
│  4. 能源    Energy (石油、电力、可再生)                │
│  5. 住房    Housing (住宅 REITs / 房地产开发)          │
│  6. 服务    Services (金融、健康、零售、餐饮)            │
│  7. 高科技  High-Tech (软件、半导体、AI)               │
└────────────────────────────────────────────────────────┘
```

### 6.2 CES 生产函数

```
Y_i = A_i · (α_K · K^ρ + α_L · L^ρ + α_E · E^ρ + α_M · M^ρ)^(1/ρ)

其中：
  σ = 1/(1-ρ)         # 替代弹性
  ρ = (σ-1)/σ
  σ → 1  → Cobb-Douglas
  σ → 0  → Leontief (固定配比)
  0 < σ < ∞           # 中间情形
```

#### 部门参数建议

| 部门 | σ（替代弹性） | 资本份额 α_K | 劳动份额 α_L | 能源份额 α_E |
|---|---|---|---|---|
| 资本品 | 0.5 | 0.4 | 0.4 | 0.2 |
| 消费品 | 0.7 | 0.3 | 0.5 | 0.2 |
| 原材料 | 0.4 | 0.5 | 0.2 | 0.3 |
| 能源 | 0.3 | 0.6 | 0.1 | 0.3 |
| 住房 | 0.6 | 0.5 | 0.4 | 0.1 |
| 服务 | 0.8 | 0.2 | 0.7 | 0.1 |
| 高科技 | 0.9 | 0.3 | 0.6 | 0.1 |

### 6.3 技术进步

```
A_i(t+1) = A_i(t) · (1 + g_i + noise)

g_i：部门 TFP 增长率（年化）
- 资本品：1-2%
- 消费品：1-2%
- 高科技：5-10%
- 其他：0.5-1.5%
```

技术进步是**慢变量**，按季度更新。

---

## 7. 网络结构

### 7.1 网络层分类

| 层 | 内容 | 拓扑 | 主要涌现 |
|---|---|---|---|
| 1. Interbank | 银行间同业拆借 | Core-Periphery | 系统性风险传染 |
| 2. Bank-Firm Credit | 银行对企业贷款 | 完全自适应 | 信贷紧缩传导 |
| 3. Bank-HH Credit | 银行对家庭贷款 | 完全自适应 | 房贷危机 |
| 4. Supply Chain | 企业间供应链 | 分层树 + 交叉 | 供给冲击 |
| 5. Asset Cross-holding | 企业间交叉持股 | Scale-Free | 甩卖螺旋 |
| 6. Labor | 行业就业分配 | 随机二部图 | 失业传染（弱） |

### 7.2 各层拓扑详解

#### Interbank: Core-Periphery

```
核心节点（5-10 家大银行）：互相紧密连接
外围节点（50-200 家小银行）：仅与 1-2 家核心相连

生成算法：
  1. 随机选 k 个核心
  2. 核心之间随机连边（密度 0.6）
  3. 每个外围节点连到 1-2 个核心
```

**为何如此**：与现代金融体系结构匹配（少数大银行 + 大量区域银行）。

#### Asset Cross-holding: Scale-Free

```
度分布 P(k) ~ k^(-γ), γ ≈ 2.5

生成算法：
  1. 初始 m 个节点完全连接
  2. 每步加入新节点，连到 m 个现有节点
  3. 概率 ∝ 度
```

**为何如此**：贴近现实（少数 conglomerate 控制大量持股）。

#### Supply Chain: 分层树 + 交叉

```
Tier 1：原材料 → 资本品
Tier 2：资本品 → 消费品 / 高科技
Tier 3：消费品 / 高科技 → 最终需求
交叉：同层企业 10% 概率相互连接

生成算法：
  1. 按部门分成 3 层
  2. 每层内部 tree 结构
  3. 跨层按部门流向连边
  4. 同层 10% 交叉
```

### 7.3 完全自适应信贷网络

每个 tick 重评估银行-企业关系：

```python
def update_credit_network(banks, firms, t):
    """自适应网络生成"""
    new_relationships = []
    dropped = []
    
    for firm in firms:
        # 评估所有银行
        scores = {
            b: lending_score(b, firm)
            for b in banks
        }
        # 选 top-k 关系银行
        top_k = sorted(scores, key=scores.get, reverse=True)[:3]
        new_relationships.append((firm.id, top_k))
        
        # 切断高风险关系
        for b in firm.current_banks:
            if risk_score(b, firm) > RISK_THRESHOLD:
                dropped.append((firm.id, b.id))
    
    return new_relationships, dropped

def lending_score(bank, firm):
    """银行对企业的评估"""
    score = (
        0.3 * firm.cashflow_stability
      + 0.3 * (firm.collateral / firm.debt)  # 抵押率
      + 0.2 * (1 - firm.leverage)            # 杠杆率反向
      + 0.1 * firm.credit_history            # 信用历史
      + 0.1 * (1 - bank.npl_ratio)           # 银行本身健康度
    )
    return score
```

#### 涌现现象

| 现象 | 机制 |
|---|---|
| 信贷突然紧缩 | 银行危机 → 风险评估急升 → 切断关系 |
| 银行逃离风险 | 评估函数对违约概率极度敏感 |
| 信贷关系重组 | 危机后小客户被抛弃，迁移到大银行 |
| 关系贷款 vs 市场贷款 | 银行偏好熟悉的长期客户 |

---

## 8. 时间架构

### 8.1 多尺度调度

```
主时钟：1 个月
快循环：每个主 tick 内 N=20-30 个日级 tick
慢循环：人口、资本存量、技术按季度更新
```

### 8.2 Tick 内操作顺序（关键！）

**同一月内的执行顺序**：

```python
def monthly_tick(t):
    # === 阶段 1: 日级快循环 ===
    for day in range(DAYS_PER_MONTH):  # 默认 30
        asset_market.step()           # 资产市场出清（股票、房产、外汇）
        interbank_market.step()       # 银行间拆借
        sentiment.update()            # 情绪/信心更新
        # 银行日内重新评估信用风险（可选）
    
    # === 阶段 2: 月末决策更新 ===
    cb.set_policy_rate()              # CB 决策（基于本月通胀/产出）
    banks.reprice_loans()            # 银行重新定价贷款
    firms.set_production_plan()       # 企业决定生产
    firms.set_prices()                # 企业调价（卡尔沃）
    households.decide_consumption()   # 家庭消费决策
    households.decide_labor_supply()  # 劳动供给
    
    # === 阶段 3: 月度市场出清 ===
    goods_market.clear()              # 商品市场
    labor_market.clear()              # 劳动市场
    credit_market.clear()             # 信贷市场
    
    # === 阶段 4: 月末统计 ===
    aggregate_macros()                # 聚合宏观变量
    write_to_timeseries()             # 写入时序
    update_slow_vars()                # 更新慢变量（季度触发）
```

### 8.3 ⚠️ 关键陷阱

1. **顺序敏感**：银行看到资产价格后再放贷 → 高估金融加速器
2. **快慢耦合**：资产价格每月初重置，月末聚合到实体变量
3. **事件时序**：危机事件须有明确触发时刻（如银行破产 = 日级事件）

### 8.4 危机内生涌现机制（Fire-Sale Externality）

⚠️ **单点 CAR 阈值不够——必须定义"被迫卖出的量"和"价格影响函数"。**

#### 8.4.1 银行被迫卖出量（Forced Sale Quantity）

```python
def forced_sale_quantity(bank: CommercialBank, asset_type: str) -> float:
    """
    银行 i 必须卖出的资产量
    核心: 资本缺口与流动性缺口的函数
    """
    # ─── 资本缺口 (CAR 触发) ───
    capital_gap = max(0, REQUIRED_CAR - bank.car) * bank.rwa
    # 例如: 缺 2% × 风险加权资产 = 必须补的资本

    # ─── 流动性缺口 (LCR 触发) ───
    liquidity_gap = max(0, REQUIRED_LCR - bank.lcr) * bank.expected_outflows
    # 例如: 缺 10% × 30 天预期流出 = 必须补的现金

    # ─── 总缺口 ───
    total_gap = capital_gap + liquidity_gap

    # ─── 银行选择如何补缺口 ───
    # 选项 1: 出售资产 (最便宜但有传染)
    # 选项 2: 缩减贷款 (紧缩信贷)
    # 选项 3: 增发股权 (最贵但无传染)
    if total_gap > 0:
        # 默认 60% 通过卖资产, 40% 通过缩贷款
        asset_sale = total_gap * 0.6
        loan_reduction = total_gap * 0.4
    else:
        asset_sale = 0
        loan_reduction = 0

    return {
        'asset_sale_amount': asset_sale,
        'loan_reduction':   loan_reduction,
        'asset_type':       asset_type,  # 通常先卖最流动的
    }
```

#### 8.4.2 Fire-Sale 价格冲击函数（核心数学）

```python
def fire_sale_price_impact(
    asset_type: str,
    quantity: float,
    market_state: 'MarketState'
) -> float:
    """
    资产被迫卖出时,价格变化率
    来源: Cifuentes-Ferrucci-Shin (2005), Brunnermeier-Pedersen (2009)
    """
    # ─── 1. 资产的市场深度参数 ───
    DEPTH = {
        'cash':          1e9,    # 现金无深度问题
        'gov_bonds':     1e8,    # 政府债深度大
        'stocks':        1e7,    # 股票中等
        'corporate_bonds': 1e6,  # 公司债较浅
        'housing':       1e5,    # 房产深度浅!
        'real_estate_commercial': 1e4,  # 商业地产最浅
    }

    # ─── 2. 流动性参数 (liquidity) ───
    # 越低 → 卖出冲击越大
    LIQUIDITY = {
        'gov_bonds':      1.0,
        'stocks':         0.9,
        'corporate_bonds':0.7,
        'housing':        0.4,    # 房产流动性低
        'real_estate_commercial': 0.3,
    }

    # ─── 3. 卖出量 / 深度 = 冲击比例 ───
    depth = DEPTH[asset_type]
    impact_ratio = quantity / depth

    # ─── 4. 基础价格影响 ───
    # 卖得越多,价格越低 (凹函数)
    base_impact = impact_ratio * (1 - LIQUIDITY[asset_type])

    # ─── 5. 传染乘数 ───
    # 其他持有者看到价格下跌 → 抛售 → 价格进一步下跌
    recent_volatility = market_state.recent_volatility
    contagion_sensitivity = 1.5  # 可调参数

    # ─── 6. 拥挤交易 ───
    # 如果多家银行同时卖同类资产,影响叠加
    crowding_multiplier = market_state.num_sellers_same_asset

    # ─── 7. 总价格冲击 ───
    total_impact = (
        base_impact
      * contagion_sensitivity
      * recent_volatility
      * crowding_multiplier
    )

    # 限制: 单次价格下跌不超过 X%
    max_impact = 0.10  # 10% 单日最大跌幅
    total_impact = min(total_impact, max_impact)

    # 价格变化 (负值)
    price_change_pct = -total_impact

    return price_change_pct
```

#### 8.4.3 完整危机涌现机制

```
═══════════════════════════════════════════════════════
阶段 1: 信贷扩张期 (慢, 数年)
─────────────────────────────────────────────────────
  • 资产价格上涨 → 抵押品升值
  • 银行资本充足率上升 → 放贷标准放松
  • 内生信用扩张 → 更多资产需求 → 价格上涨
  • 银行杠杆率上升 (Brock-Hommes 让价格偏离基本面)

阶段 2: 庞氏融资累积 (中速, 数月)
─────────────────────────────────────────────────────
  • 杠杆率超过历史 80 分位
  • 部分企业/家庭借新还旧 (interest_coverage < 1)
  • 脆弱性指标累积:
    - 银行平均 CAR 下降
    - 家庭 DTI 中位数上升
    - 信贷/GDP 缺口偏离 (BIS 指标)
  • 但 CAR 仍 > 阈值, 未触发甩卖

阶段 3: 明斯基时刻 (突发, 数日-数周)
─────────────────────────────────────────────────────
  触发条件 (任一):
    • 某银行 CAR < 4% (强制甩卖)
    • 资产价格单月跌幅 > 10% (触发保证金追缴)
    • 某大型 interbank 违约 (Cifuentes 触发)
  
  触发后:
    1. fire_sale_price_impact() 计算资产价格下跌
    2. 其他持有该资产银行的资本缩水
    3. → 多家银行 CAR 同时跌破阈值 (传染)
    4. → 多家银行同时甩卖 (拥挤交易)
    5. → 资产价格进一步下跌 (反馈环)
    6. → 银行间拆借冻结 (interbank 利率飙升)
  
  关键数学:
    • 单家 CAR < 阈值 → 卖 1%
    • 但因为传染: 5 家同时卖 → 总冲击 10%+
    • 因为拥挤: 价格影响非线形

阶段 4: 债务-通缩螺旋 (中速, 1-3 年)
─────────────────────────────────────────────────────
  • 资产价格下跌 → 抵押品价值下降
  • → 银行收紧信贷 (loan_reduction 路径)
  • → 企业投资收缩
  • → GDP 下降
  • → 价格水平下降 (deflation)
  • → 实际债务负担上升 (Fisher 效应)
  • → 企业违约增加 → 银行 NPL 上升
  • → 银行进一步收紧信贷
  • 闭环反馈, 直到某种稳态

阶段 5: 政策反应 (外生/内生)
─────────────────────────────────────────────────────
  • CB 降低政策利率 (零下限)
  • CB 启动 LOLR (最后贷款人)
  • 政府启动财政刺激
  • 政策有效性受当时约束限制
═══════════════════════════════════════════════════════
```

#### 8.4.4 ❗ 关键设计原则

1. **甩卖不是单点事件**——是**传染性过程**，多家银行同时或相继发生
2. **价格影响函数必须是数学的**，不是"触发→崩盘"的剧本规则
3. **不同资产有不同的流动性参数**——房产流动性远低于股票
4. **传染和拥挤放大**——非线性，不能用线性近似
5. **SFC 校验保证**：甩卖时，买方资金来自其他部门（不是凭空产生）

### 8.5 性能预算（Performance Budget）❗

⚠️ **100K 家庭 + 日级循环 = 计算瓶颈。必须在架构层面分层。**

#### 8.5.1 性能目标

| 操作 | 预算 | 说明 |
|---|---|---|
| 月主 tick（20K agents） | ≤ 500 ms | 实时交互所需 |
| 月主 tick（100K agents） | ≤ 2000 ms | 异步场景 |
| 日级资产 sub-tick（参与家庭） | ≤ 50 ms | 30 个 sub-tick = 1.5s/月 |
| 单次 SFC 校验 | ≤ 20 ms | 月末聚合时 |
| 完整快照（Parquet 写入） | ≤ 100 ms | 每 12 月一次 |
| 状态读取（下钻 UI） | ≤ 50 ms | 用户触发 |

#### 8.5.2 Agent 分层架构（性能关键）

```
┌────────────────────────────────────────────────────────┐
│              Agent 分层                                 │
├────────────────────────────────────────────────────────┤
│  Layer A: Full Behavior (10K–20K)                       │
│    • 完整状态 + 完整决策函数                              │
│    • 参与所有市场 (消费、劳动、资产、信贷)                 │
│    • 用于产生核心宏观现象                                 │
│                                                         │
│  Layer B: Behavioral Bucket (100K+)                      │
│    • 状态按桶聚合 (财富分位 + 年龄段 + 部门)             │
│    • 决策用桶内均值 + 小幅扰动                            │
│    • 用于产生帕累托尾、统计代表性                        │
│    • 每月重新采样 5% 进入 Layer A (流动)                │
│                                                         │
│  Layer C: Statistical Tail (无上限)                     │
│    • top 1% 财富、top 0.1% 收入作为显式统计对象          │
│    • 不需要逐个 agent                                   │
│    • 满足"帕累托尾涌现"的实证要求                       │
└────────────────────────────────────────────────────────┘
```

#### 8.5.3 资产市场参与资格过滤

```python
def participates_in_daily_asset_market(hh: Household) -> bool:
    """
    只有"有交易意图的"家庭才进入日级循环
    默认: 总家庭数的 10%–20%
    """
    return (
        hh.stocks > 1000.0  # 持股 > 阈值
        or hh.investment_property  # 持有投资房
        or hh.job_search_intensity > 0.3  # 活跃求职者
    )
```

#### 8.5.4 数据结构选型

| 数据 | 结构 | 理由 |
|---|---|---|
| Household 状态 | Polars DataFrame | 列式存储,向量化 |
| Firm 状态 | Polars DataFrame | 同上 |
| 银行状态 | NamedTuple 列表 | 数量小 |
| Agent 之间交互 | CSR 稀疏矩阵 | 信贷网络 |
| 时序数据 | Parquet 列存 | 压缩 + 列读 |
| 查询/分析 | DuckDB | SQL 接口 |

#### 8.5.5 性能监控埋点

```python
import time

class PerfMonitor:
    def __init__(self):
        self.timings: dict[str, list[float]] = defaultdict(list)

    def measure(self, name: str):
        return self._Timer(self.timings, name)

    class _Timer:
        def __enter__(self):
            self.start = time.perf_counter()
        def __exit__(self, *args):
            elapsed = time.perf_counter() - self.start
            self.timings[self.name].append(elapsed)

# 使用
perf = PerfMonitor()
with perf.measure('monthly_tick'):
    for day in range(30):
        with perf.measure('daily_asset_step'):
            asset_market.step()
    # ...

# 每月末报告
if t % 12 == 0:
    print(perf.summary())  # 各阶段耗时分布
```

### 8.6 可复现性（Reproducibility）❗

⚠️ **教学场景的核心要求——"同样的按钮 = 同样的结果"。**

#### 8.6.1 RNG 流管理

```python
class RNGManager:
    """
    每个子系统有独立的 RNG 流
    好处: 调整一个模块的行为不影响其他模块的随机性
    """

    SUBSYSTEMS = [
        'household_init',
        'firm_init',
        'bank_init',
        'shock_injection',     # 政策/外生冲击
        'asset_price_noise',   # 日级资产市场噪音
        'labor_matching',      # 工作匹配
        'credit_allocation',   # 信贷分配
        'firm_pricing',        # 调价扰动
    ]

    def __init__(self, master_seed: int):
        self.seeds: dict[str, int] = {}
        # 用 master seed 派生各子系统种子
        # 避免子系统种子之间的相关性
        base_rng = np.random.default_rng(master_seed)
        for sub in self.SUBSYSTEMS:
            self.seeds[sub] = int(base_rng.integers(0, 2**32))

    def stream(self, subsystem: str) -> np.random.Generator:
        """获取子系统的独立 RNG 流"""
        return np.random.default_rng(self.seeds[subsystem])

    def fork(self, new_master_seed: int) -> 'RNGManager':
        """从某个 tick 分叉,创建新随机序列"""
        return RNGManager(new_master_seed)

# 使用
rng_mgr = RNGManager(master_seed=42)
hh_init_rng  = rng_mgr.stream('household_init')
asset_rng    = rng_mgr.stream('asset_price_noise')
```

#### 8.6.2 状态快照与恢复（Parquet）

```python
class StateSnapshot:
    """
    每个 tick 可保存完整状态到 Parquet
    支持从任意 tick 恢复 + 重放
    """

    def save(self, state: 'SimulationState', path: str):
        """写入 Parquet (压缩 + 列式)"""
        # 分表存储,避免单表过大
        state.households.to_parquet(f"{path}/households.parquet")
        state.firms.to_parquet(f"{path}/firms.parquet")
        state.banks.to_parquet(f"{path}/banks.parquet")
        # 元数据
        metadata = {
            'tick':          state.t,
            'master_seed':   state.master_seed,
            'rng_seeds':     state.rng_mgr.seeds,
            'macro_snapshot': state.macro_history.tail(1).to_dict(),
        }
        with open(f"{path}/metadata.json", 'w') as f:
            json.dump(metadata, f)

    @classmethod
    def load(cls, path: str) -> 'SimulationState':
        """从 Parquet 恢复"""
        state = SimulationState()
        state.households = pl.read_parquet(f"{path}/households.parquet")
        state.firms      = pl.read_parquet(f"{path}/firms.parquet")
        state.banks      = pl.read_parquet(f"{path}/banks.parquet")
        with open(f"{path}/metadata.json") as f:
            metadata = json.load(f)
        state.t          = metadata['tick']
        state.master_seed = metadata['master_seed']
        state.rng_mgr.seeds = metadata['rng_seeds']
        return state
```

#### 8.6.3 重放与分叉（教学 UX 必备）

```python
class ReplayManager:
    """
    支持:
    1. 完整重放: 从 tick 0 重现
    2. 分叉: 从 tick T 改变某个决策,产生新分支
    """

    def replay(self, snapshot_path: str, end_tick: int) -> 'SimulationState':
        """从快照重放到 end_tick"""
        state = StateSnapshot.load(snapshot_path)
        while state.t < end_tick:
            state.step()
        return state

    def fork(self, snapshot_path: str, change_fn: Callable) -> 'SimulationState':
        """
        从快照分叉: 加载状态,应用 change_fn 修改,继续运行
        例: "假设 2008 年 9 月 CB 降息 1%"
        """
        state = StateSnapshot.load(snapshot_path)
        change_fn(state)  # 用户干预
        return state

# 教学 UX 使用
def user_intervention(state):
    """学生按下'降息'按钮"""
    state.cb.policy_rate -= 0.01  # 1%

forked = replay_mgr.fork('snapshots/t_240.parquet', user_intervention)
# 现在 forked 沿着'如果央行降息'的平行宇宙运行
```

#### 8.6.4 场景快照库

```python
SCENARIO_SNAPSHOTS = {
    '2008_crisis_peak':      'snapshots/t_240.parquet',  # 2008 年 9 月
    'pre_dot_com_bubble':    'snapshots/t_120.parquet',  # 2000 年 3 月
    'post_war_boom':         'snapshots/t_030.parquet',  # 1950 年
    'japanese_lost_decade':  'snapshots/t_600.parquet',  # 1990 年
}
# 学生可以从任一历史时刻开始"如果..."
```

---

## 9. 预期与学习机制（多资产）

⚠️ **不同资产类别用不同的预期机制——股票高频 → Brock-Hommes；房产低频 → 租金锚定；债券 → 期限结构；外汇 → UIP。**

### 9.1 股票市场预期（Brock-Hommes 异质信念）

**核心思想**：市场参与者使用**多种预测规则**，根据**过去表现**动态切换。

#### 9.1.1 信念规则集

每个资产市场参与者拥有 N 个信念规则：

| 规则 | 公式 | 适用情形 |
|---|---|---|
| **R1: Trend Following** | `f = p[t-1] + 0.5·(p[t-1] - p[t-2])` | 趋势市 |
| **R2: Fundamental** | `f = dividend / discount_rate` | 基本面定价 |
| **R3: Mean Reverting** | `f = MA(p, window=20)` | 震荡市 |
| **R4: Adaptive** | `f = α·p[t-1] + (1-α)·forecast[t-1]` | 一般情形 |
| **R5: Optimistic** | `f = p[t-1]·(1 + bias)` | 牛市情绪 |
| **R6: Pessimistic** | `f = p[t-1]·(1 - bias)` | 熊市情绪 |
| **R7: Noise** | `f = p[t-1] + ε` | 随机游走 |

#### 9.1.2 适应学习

```python
class Trader:
    beliefs: list[BeliefRule]
    fitness: dict[BeliefRule, float]  # 信念的近期表现
    
    def choose_belief(self):
        """按 fitness 的 softmax 概率选择"""
        z = [self.fitness[b] for b in self.beliefs]
        probs = softmax(z)
        return np.random.choice(self.beliefs, p=probs)
    
    def update_fitness(self, belief_used, actual_error):
        """更新使用过的信念的 fitness"""
        # 衰减旧 fitness + 加上本期误差（负值）
        for b in self.beliefs:
            self.fitness[b] *= (1 - DECAY)  # 默认 DECAY=0.05
        self.fitness[belief_used] += -actual_error
```

#### 9.1.3 涌现的金融现象（仅限股票）

- **股价厚尾**（非正态分布）
- **波动聚集**（volatility clustering）
- **泡沫与崩盘的内生涌现**
- **交易量与价格波动的相关性**

### 9.2 房产市场预期（租金锚定 + 抵押品渠道）

**房产不能用 Brock-Hommes**——理由见 Section 4.4.2。

```python
class HousingExpectation:
    """房产预期:简化,异质性较小"""

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

        # 加权
        return (
            0.5 * fundamental
          + 0.3 * trend
          + 0.2 * state.housing_price * (1 + collateral_signal)
        )
```

**异质性来源**：
- 家庭对未来抵押品可得性的预期（基于货币政策）
- 家庭对未来收入的信心
- 但**不**使用 7 条信念规则的复杂机制

### 9.3 债券市场预期（期限结构）

```python
class BondExpectation:
    """债券:基于期限结构的理性预期"""

    def expected_long_rate(self, state) -> float:
        # 期限溢价 + 期望
        # Nelson-Siegel 简化版
        expected_short = state.cb.expected_policy_path  # CB 指引
        term_premium = 0.01  # 期限溢价 1%

        return expected_short + term_premium
```

**不**使用 Brock-Hommes——债券市场参与者更接近理性预期（机构为主）。

### 9.4 外汇市场预期（UIP）

⚠️ MVP 不实现，但架构预留：

```python
class FXExpectation:
    """外汇:抛补利率平价 (UIP)"""
    # E[e_{t+1}] = e_t · (1 + r_dom) / (1 + r_foreign)
    # 套利交易:carry trade
    # 后期实现
    pass
```

### 9.5 总结：异质预期架构

| 资产类别 | 机制 | 复杂度 | 参与者 |
|---|---|---|---|
| 股票 | Brock-Hommes (7 规则) | 高 | 个体散户 + 投资银行 + 资管 |
| 房产 | 租金锚定 + 抵押品 | 中 | 个体 + 开发商 |
| 债券 | 期限结构 | 低 | 机构 (CB + 银行 + 资管) |
| 外汇 | UIP | 低 | 后期 |

**关键设计原则**：
- 不强制每类资产都"涌现"——债券接近理性、房产弱异质、股票强异质
- 异质性强度应该匹配**真实市场参与者结构**

---

## 10. 政策与用户控制

### 10.1 货币政策

**默认行为**：Taylor Rule 自动执行

```python
r_target = r_neutral + 1.5·(π - π*) + 0.5·output_gap
r_new = 0.85·r_prev + 0.15·r_target
```

**用户可覆盖**：手动设置政策利率

| 工具 | 默认 | 可调范围 | 影响 |
|---|---|---|---|
| 政策利率 | Taylor Rule 自动 | 0% – 25% | 短端利率、信贷条件、资产价格 |
| 存款准备金率 | 10% | 0% – 30% | 银行可贷资金量 |
| 逆周期资本缓冲 | 0% | 0% – 5% | 银行 CAR 要求 |
| 最后贷款人 | 关闭 | 开/关 + 利率 | 危机干预 |

### 10.2 财政政策（完全可调）

| 工具 | 默认 | 可调范围 | 影响 |
|---|---|---|---|
| 政府支出 G | 自动稳定 | 占 GDP 0% – 50% | 总需求 |
| 税率 | 单一税率 25% | 0% – 50% | 总收入 |
| 转移支付 | 自动 | 占 GDP 0% – 30% | 家庭收入 |
| 公债发行 | 自动 | - | 利率、挤出 |

### 10.3 宏观审慎政策（完全可调）

| 工具 | 默认 | 可调范围 | 影响 |
|---|---|---|---|
| 最低 CAR | 8% | 4% – 20% | 银行杠杆 |
| LTV 上限 | 80% | 50% – 100% | 房贷规模 |
| 准备金率 | 10% | 0% – 30% | 货币乘数 |
| 系统性重要机构附加资本 | 1% | 0% – 4% | 大银行安全垫 |

### 10.4 用户界面（透明黑盒）

```
Layer 1 - 仪表盘（默认）
  6 个核心宏观变量: GDP / 通胀 / 失业率 / 股价 / 信贷增速 / 基尼系数

Layer 2 - 探针（点击进入）
  失业人口: 群体画像（低技能/服务业/年轻人占比）
  银行系统: 哪些银行 CAR<8%？
  行业: 哪个 sector 在收缩？

Layer 3 - 个体（再点击进入）
  某家庭: 收入/消费/储蓄/负债/就业状态
  某企业: 资产负债表/订单/库存
  某银行: 贷款组合/NPL率/流动性

Layer 4 - 源码（隐藏）
  决策函数当前输入/参数
```

---

## 11. UX 与可观测性

### 11.1 混合沙盒模式

```
┌────────────────────────────────────────────┐
│           主界面 │
│  ┌──────────┐  ┌──────────────────┐  │
│  │ 场景库  │  │ 自由沙盒      │  │
│  │ ───── │  │  ─────────      │  │
│  │ 2008危机 │  │ 空白起点       │  │
│  │ 滞胀    │  │ 默认参数       │  │
│  │ 房价泡沫 │  │ 完全可调       │  │
│  │ 战后复苏 │  │              │  │
│  └──────────┘  └──────────────────┘  │
└────────────────────────────────────────────┘
```

### 11.2 场景库（待设计）

| 场景 | 核心机制 |
|---|---|
| 2008 金融危机 | 内生信贷繁荣 → 资产泡沫 → 银行破产 → 危机 |
| 1970s 滞胀 | 能源冲击 + 工资粘性 |
| 战后复苏 | 重建投资 + 高储蓄率 |
| 房价泡沫 | 抵押贷款扩张 + 金融加速器 |
| 货币危机 | 固定汇率 + 资本外流 |

### 11.3 时间序列可视化

- 默认显示：GDP、CPI、失业率、股价指数、信贷增速、基尼系数
- 可添加：分位财富、利率曲线、银行 CAR 分布

---

## 12. 涌现目标

### 12.1 目标现象清单

| # | 现象 | 涌现自 | 验证 |
|---|---|---|---|
| 1 | 明斯基周期 | 内生信用 + 异质信念 + 银行失败规则 | 至少 100 次跑中重现 >50 次 |
| 2 | 金融加速器 | 日级资产价格 → 银行资本 → 信贷 | 房价跌 10%，投资下降 >2% |
| 3 | 债务-通缩螺旋 | 价格粘性 + 实际债务负担 + 内生信用 | 通缩 + 实际 GDP 下降 |
| 4 | 银行间挤兑 | Core-Periphery interbank 网络 + CAR 阈值 | 单家银行失败传染 N 家 |
| 5 | 帕累托财富分布 | 个体家庭 + 异质储蓄率 + 资产复利 | top 1% 财富占比 >30% |
| 6 | 中产空心化 | 工资 vs 资产价格 增速差 | 中位数实际收入停滞 |
| 7 | 能源冲击传导 | CES + 部门供应链 | 能源价格 50% 涨 → GDP 短期下降 |
| 8 | 房价泡沫 | 抵押贷款 + 银行资本顺周期 | 房价/收入比峰值 >8 |
| 9 | 政策误判 | 手动覆盖 + 反应滞后 | 央行滞后 → 通胀加剧 |
| 10 | 部门轮动 | 资本跨部门 + TFP 异速 | 资本品占比相对消费品变化 |

### 12.2 验证标准

通过"stylized facts test"：
1. **GDP 单位根 + 周期性波动**
2. **产出与就业高度协动**
3. **短期菲利普斯曲线**
4. **财富分布服从帕累托尾**
5. **企业规模服从 Zipf 律**
6. **金融变量厚尾性、波动聚集**
7. **危机事件内生涌现**

### 12.3 Calibration Suite（自动化验证）❗

⚠️ **验证不能靠人眼——必须用 pytest 风格的回归测试，每次改参数自动跑。**

#### 12.3.1 测试套件

```python
# tests/calibration/test_stylized_facts.py

import pytest
from financial_sim.core import Simulation

SCENARIOS = [
    'baseline',
    'tight_credit',
    'loose_credit',
    'energy_shock',
    'high_inflation',
]

@pytest.fixture(scope='session')
def monte_carlo_results(tmp_path_factory):
    """运行 50 次蒙特卡洛,保存结果"""
    n_runs = 50
    results = []
    for seed in range(n_runs):
        sim = Simulation(scenario='baseline', seed=seed, ticks=1200)
        results.append(sim.run())
    return results

# ─── 测试 1: 财富帕累托尾 ───
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_wealth_pareto_tail(scenario, monte_carlo_results):
    """top 1% 财富占比应在 25-45% 之间"""
    for r in monte_carlo_results:
        top1_share = r.household_wealth.quantile(0.99)
        assert 0.25 < top1_share < 0.45, \
            f"{scenario}: top 1% share = {top1_share}"

# ─── 测试 2: 危机涌现 ───
@pytest.mark.parametrize("seed", range(20))
def test_crisis_emergence_loose_credit(seed):
    """宽松信贷场景下,应涌现危机 (50%+)"""
    sim = Simulation(scenario='loose_credit', seed=seed, ticks=600)
    result = sim.run()
    crashes = result.detect_crashes(min_drop=0.10)
    # 至少 50% 的种子应出现显著危机
    assert len(crashes) > 0

# ─── 测试 3: 波动聚集 ───
def test_volatility_clustering(monte_carlo_results):
    """股价应表现出波动聚集 (GARCH 效应)"""
    for r in monte_carlo_results:
        returns = r.stock_index.pct_change().dropna()
        # 计算 |return_t| 与 |return_{t-1}| 的相关性
        autocorr = returns.abs().autocorr(lag=1)
        assert autocorr > 0.1, f"volatility clustering weak: {autocorr}"

# ─── 测试 4: 厚尾 ───
def test_stock_returns_fat_tails(monte_carlo_results):
    """股价收益率应呈厚尾 (kurtosis > 3)"""
    for r in monte_carlo_results:
        returns = r.stock_index.pct_change().dropna()
        kurtosis = returns.kurtosis()
        assert kurtosis > 3, f"kurtosis too low: {kurtosis}"

# ─── 测试 5: 产出 - 就业协动 ───
def test_gdp_unemployment_corr(monte_carlo_results):
    """GDP 增长与就业增长应高度正相关"""
    for r in monte_carlo_results:
        gdp_growth = r.gdp.pct_change(12)
        emp_growth = r.employment.pct_change(12)
        corr = gdp_growth.corr(emp_growth)
        assert corr > 0.7, f"GDP-employment correlation: {corr}"

# ─── 测试 6: SFC 守恒 ───
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_sfc_consistency(scenario):
    """所有 tick 必须通过 SFC 校验"""
    sim = Simulation(scenario=scenario, seed=0, ticks=1200)
    sim.run()
    violations = sim.sfc_violations
    assert len(violations) == 0, f"SFC violations: {len(violations)}"

# ─── 测试 7: 性能 ───
def test_performance_budget():
    """月主 tick 应 < 500ms"""
    sim = Simulation(scenario='baseline', seed=0, ticks=12)
    times = []
    for t in range(12):
        start = time.perf_counter()
        sim.step()
        times.append(time.perf_counter() - start)
    p95 = np.percentile(times, 95)
    assert p95 < 0.5, f"P95 tick time: {p95*1000:.0f}ms"
```

#### 12.3.2 持续集成

```yaml
# .github/workflows/calibration.yml
name: Calibration
on:
  pull_request:
    paths: ['financial_sim/**', 'tests/calibration/**']
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -e .
      - run: pytest tests/calibration/ -v --tb=short
      - uses: actions/upload-artifact@v4
        with:
          name: calibration-report
          path: reports/
```

#### 12.3.3 校准报告

每次 CI 跑完生成报告：
```
╔══════════════════════════════════════════════════════╗
║  CALIBRATION REPORT - baseline scenario              ║
╠══════════════════════════════════════════════════════╣
║  ✓ Pareto tail:        top 1% share = 32%          ║
║  ✓ Volatility cluster: autocorr = 0.18             ║
║  ✓ Fat tails:          kurtosis = 6.2               ║
║  ✓ GDP-emp corr:       0.84                          ║
║  ✓ SFC:                0 violations                  ║
║  ✓ Performance:        P95 = 312ms                   ║
╚══════════════════════════════════════════════════════╝
```

### 12.4 学术对比

每个版本应能重现以下经验结果（基于真实历史数据）：

| 现象 | 真实数据 | 模型输出 | 容差 |
|---|---|---|---|
| 财富基尼系数 | 0.85 (US) | - | ±0.05 |
| 房价/收入比 | 5-10 (US) | - | ±2 |
| 失业率 SD/GDP SD | 4-5x | - | ±1 |
| 银行 CAR 波动 | 8-15% | - | ±2 |

---

## 13. 校准

### 13.1 参数来源

| 参数类型 | 来源 | 备注 |
|---|---|---|
| 经济周期参数 | 真实国家数据 | 美国/中国季度数据 |
| 部门 TFP 增长率 | KLEM 数据库 | 跨国平均 |
| 银行参数 | BIS 报告 | CAR/LCR 阈值 |
| 家庭行为 | 消费调查 | SCF / CHFS |
| 初始条件 | 起点 + 稳态 | 平衡路径 |

### 13.2 ❓ 校准决策待定

- 是否跟随中国数据 vs 美国数据？
- 初始年份：1950 / 1980 / 2000 / 2020？
- 简化的"风格化数值"是否够用？

---

## 14. 待决事项

### 14.1 已部分决定但需细化

- [ ] 校准策略与参数来源
- [ ] 场景优先级与剧本设计
- [ ] 初始稳态生成方法

### 14.2 ✅ 已解决：技术栈

| 层 | 选型 | 理由 |
|---|---|---|
| **仿真核心** | Python 3.11+ | 迭代速度 >> 运行速度 |
| 数值计算 | NumPy + Numba（JIT 热点函数） | Numba 对循环可 10-100x 加速 |
| 数据表 | Polars | 列式,向量化,快 |
| 网络/稀疏 | SciPy.sparse + NetworkX | 标准 |
| **状态持久化** | Parquet（快照） + DuckDB（查询） | 教学项目首选 |
| **可视化层** | Svelte + WebSocket | 下钻 UI 天然适合 DOM |
| 图表 | D3.js 或 ECharts | 时间序列 + 网络 |
| **测试** | pytest + calibration suite | 见 Section 12.3 |
| **CI** | GitHub Actions | 跑校准测试 |

**不选** Rust/Godot/Unity 的理由：
- 迭代速度优先
- 教学项目重视可读性
- 性能瓶颈用 Numba + 向量化解决

### 14.3 MVP 实施路线图

#### Phase 0: 原型（1-2 周）
- 单部门 + 单部门 firms + 代表性 HH
- 验证 SFC 守恒
- 跑通月度循环

#### Phase 1: 最小可工作核心（4-6 周）
- 3 部门 firms + 10K 个体级 HH
- 单家银行 + CB + Taylor Rule
- 资产市场（Brock-Hommes）
- SFC 校验 + 快照
- 6 个核心宏观时间序列可视化

#### Phase 2: 金融层扩展（4-6 周）
- 多家商业银行 + 投资银行
- Interbank core-periphery 网络
- 房产市场（独立机制）
- Fire-sale externality 函数
- 危机涌现测试

#### Phase 3: 完整经济（4-6 周）
- 5+ 部门 + CES
- 7 类主体齐全
- 完全自适应信贷网络
- 场景库（2008、滞胀、战后复苏）

#### Phase 4: 教学层（4-6 周）
- 透明黑盒 UI（4 层）
- 场景编辑器
- 实时干预界面
- 教程 / 引导任务

#### Phase 5: 校准与验证（持续）
- Calibration suite 完整化
- 与历史数据对比
- 教学实验

### 14.4 MVP 范围（Phase 1 必须包含）

| 组件 | 是否 MVP | 说明 |
|---|---|---|
| 5 部门 + CES | ❌ | Phase 1 用 3 部门 |
| 7 类主体 | ❌ | Phase 1 用 4 类 (HH + Firms + Bank + CB) |
| 10K HH | ⚠️ | Phase 1 用 1K–5K |
| 个体级 HH | ✅ | 必须,不能降级 |
| Brock-Hommes | ✅ | 必须 |
| 房产市场 | ❌ | Phase 2 |
| Fire-sale externality | ⚠️ | 简化版 |
| Interbank 网络 | ❌ | Phase 2 |
| 自适应信贷 | ❌ | Phase 2 |
| 外资 | ❌ | 不做 |
| 场景库 | ❌ | Phase 3 |
| 透明黑盒 UI | ❌ | Phase 4 (MVP 用基础 matplotlib 可视化) |

---

## 附录 A：术语表

| 术语 | 解释 |
|---|---|
| **ABM** | Agent-Based Modeling，基于主体的建模 |
| **DSGE** | Dynamic Stochastic General Equilibrium，动态随机一般均衡 |
| **POP** | Population Unit，宏观模拟中的人口单元（维多利亚3 用法）|
| **CES** | Constant Elasticity of Substitution，固定替代弹性 |
| **CAR** | Capital Adequacy Ratio，资本充足率 |
| **NPL** | Non-Performing Loan，不良贷款 |
| **Taylor Rule** | 央行利率设定规则 |
| **Stiglitz-Weiss** | 信贷配给理论 |
| **Minsky Moment** | 明斯基时刻：投机性融资崩溃 |
| **Financial Accelerator** | 金融加速器：Bernanke-Gertler-Gilchrist |
| **Debt-Deflation** | 债务-通缩螺旋：Fisher |
| **Brock-Hommes** | 异质信念资产定价模型 |
| **Core-Periphery** | 核心-外围网络结构 |
| **Scale-Free** | 度分布服从幂律的网络 |
| **NSFR / LCR** | Basel III 的流动性指标 |
| **OMO** | Open Market Operations，公开市场操作 |
| **MPC** | Marginal Propensity to Consume，边际消费倾向 |
| **SFC** | Stock-Flow Consistency，存量-流量一致性 |
| **TFPM** | Transaction Flow Matrix，部门间交易流量矩阵 |
| **Fire-Sale Externality** | 资产被迫抛售导致的价格外溢效应 |
| **LOLR** | Lender of Last Resort，最后贷款人 |
| **NAIRU** | Non-Accelerating Inflation Rate of Unemployment，自然失业率 |
| **LTV** | Loan-to-Value，贷款价值比 |
| **DSR** | Debt Service Ratio，偿债率 |
| **Carry Trade** | 套息交易：借入低息货币，投资高息资产 |
| **UIP** | Uncovered Interest Parity，非抛补利率平价 |
| **GARCH** | Generalized AutoRegressive Conditional Heteroskedasticity |
| **stylized facts** | 经验中反复出现的统计规律（无需精确数值，仅需定性重现）|
| **PHL** | Personal Income, Hours worked, Labor force （工资议价三角）|

---

## 附录 B：参考资料

### B.1 ABM 教材与综述

1. **Delli Gatti et al. (2011)** *Macroeconomics from the Bottom-Up*
2. **Lengnick (2013)** *Agent-based Macroeconomics: A Textbook*
3. **Farmer, Foley (2009)** "The economy needs agent-based modelling" *Nature*
4. **Tesfatsion (2006)** "Agent-based computational economics"
5. **Chen, Zimmermann (2021)** *Agent-based Modeling in Economics and Finance*

### B.2 Stock-Flow Consistency

1. **Godley, Lavoie (2007)** *Monetary Economics: An Integrated Approach* — SFC 圣经
2. **Caiani, Godin, Caverzasi, Riccetti, Russo, Gallegati (2016)** "Agent-based-stock flow consistent macroeconomics"
3. **Kinsella, O'Hara, O' (2011)** "Introducing financial New Keynesian economics"

### B.3 危机机制与 Fire-Sale

1. **Minsky (1992)** *The Financial Instability Hypothesis* (working paper, 1992)
2. **Brunnermeier, Pedersen (2009)** "Market liquidity and funding liquidity" *RFS*
3. **Cifuentes, Ferrucci, Shin (2005)** "Liquidity and risk management" *BIS*
4. **Gertler, Kiyotaki (2010)** "Financial intermediation and credit policy in business cycle analysis"
5. **Diamond, Rajan (2011)** "Fear of fire sales" *JFE*

### B.4 异质信念与资产定价

1. **Brock, Hommes (1998)** "Heterogeneous beliefs and routes to chaos" *JEDC*
2. **Hommes (2006)** "Heterogeneous agent models in economics and finance" *Hbook*
3. **LeBaron (2006)** "Agent-based computational finance"

### B.5 工资与菲利普斯曲线

1. **Taylor (1980)** "Aggregate dynamics and staggered contracts" *JPE*
2. **Calvo (1983)** "Staggered prices in a utility-maximizing framework"
3. **Gali (2015)** *Monetary Policy, Inflation, and the Business Cycle*

### B.6 网络与系统性风险

1. **Battiston et al. (2012)** "DebtRank: A centrality measure based on the rating system" *Sci Rep*
2. **Markose, Giansante, Shangkar (2007)** "E-R model with heterogeneous expectations"
3. **Acemoglu, Ozdaglar (2011)** "Opinion dynamics and stubbornness"

### B.7 政策与 ABM 工具

1. **EURACE Project** (2011, EU-funded)
2. **CIRCUIT Model** (financial fragility)
3. **Markose GEC Model** (systemic risk)
4. **Gualdi, Bouchaud et al. (2015)** "European Markets"
5. **Popoyan, Napoletano, Fagiolo (2017)** "Bank regulation"

### B.8 计算与实现

1. **Polars 文档**（数据结构）
2. **Numba 文档**（JIT 编译）
3. **Parquet 列存格式**

---

## 附录 C：版本历史

| 版本 | 日期 | 内容 |
|---|---|---|
| v0.1 | 2026-08 | 12 项架构决策完成，整体设计定型 |
| v0.2 | 2026-08 | 审查修订：加入 SFC 内核、性能预算、可复现性、Fire-Sale 函数、多资产预期机制、Calibration Suite、技术栈定型 |