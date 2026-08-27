# 主体层设计（Agents）

> 返回：[DESIGN.md](../DESIGN.md)
> 版本：v0.2 | 2026-08-27

---

## 3.1 主体分类

| # | 主体 | 数量 | 粒度 | 说明 |
|---|---|---|---|---|
| 1 | Households（家庭） | 10K–100K | 个体级 | MVP 1K–5K |
| 2 | Firms（企业） | 6 部门 × ~100 | 个体级 | MVP 3 部门 |
| 3 | Commercial Banks（商业银行） | 10–200 | 个体级 | MVP 1 家 |
| 4 | Investment Banks（投资银行） | 3–10 | 个体级 | Phase 2 |
| 5 | Asset Funds / Insurance（资管/保险） | 5–20 | 个体级 | Phase 2 |
| 6 | Government（政府） | 1 | 总量 | MVP 必需 |
| 7 | Central Bank（中央银行） | 1 | 总量 | MVP 必需 |
| 8 | Foreign Sector（外资） | 1 | 总量 | 可选模块 |

---

## 3.2 Households（家庭）

**粒度**：个体级，每个家庭是独立 agent。

### 3.2.1 状态字段

```python
@dataclass
class Household:
    id: str

    # ── 人口学 ──
    age: int
    education: float          # 0–1, 影响工资与就业机会
    household_size: int       # 负担人数

    # ── 就业 ──
    sector: str | None        # 当前就职部门
    wage: float
    employed: bool
    tenure: float             # 工龄，影响失业成本
    unemployment_duration: int  # 失业持续期，影响人力资本（疤痕效应）

    # ── 金融 ──
    wealth: float             # 净资产
    income: float             # 可支配收入
    consumption: float
    savings_rate: float       # 异质!
    debt: float               # 房贷 + 消费贷
    debt_to_income: float

    # ── 资产持仓 ──
    deposits: float           # 银行存款
    stocks: float             # 股票市值
    bonds: float              # 债券市值
    housing_units: int        # 自住房数量
    investment_property: int  # 投资性房产数量

    # ── 行为参数（异质性源头）──
    marginal_propensity_to_consume: float
    risk_tolerance: float     # 影响资产配置
    job_search_intensity: float
    credit_constraint: float  # 最大可借（银行评估）
```

### 3.2.2 行为规则

#### 1. 消费决策 🆕（改进版）

```python
def household_consumption(hh: Household, state: 'SimulationState') -> float:
    """
    有信贷约束的永久收入消费
    三通道: 永久收入 + 财富效应 + 流动性约束
    """
    # ─── 永久收入通道 ───
    # 永久收入 = 过去收入的指数加权平均
    permanent_income = (
        0.7 * hh.permanent_income_prev
      + 0.3 * hh.income
    )
    desired_consumption = hh.mpc * permanent_income

    # ─── 财富效应通道 ───
    # 资产价格上涨 → 家庭感觉更富 → 消费增加
    wealth_effect_coeff = 0.03  # 约 3 cents per dollar（实证典型值）
    wealth_effect = wealth_effect_coeff * hh.wealth

    # ─── 总期望消费 ───
    desired = desired_consumption + wealth_effect

    # ─── 流动性约束 ───
    # 低财富家庭无法平滑消费（关键不平等机制）
    available_resources = hh.income + hh.deposits - hh.debt_service
    actual = min(desired, max(available_resources, MIN_CONSUMPTION))

    return actual
```

#### 2. 储蓄/投资决策

```python
# 剩余财富 → 按风险偏好分配到资产市场
# risk_tolerance 高 → 更多股票/房产
# risk_tolerance 低 → 更多存款/债券
```

#### 3. 劳动供给

```python
# 根据工资率与保留工资决定是否找工作
# 保留工资 = f(失业救济, 家庭负担, 搜寻成本)
# 搜寻强度 = job_search_intensity × (当前工资 - 保留工资) / 保留工资
```

#### 4. 信贷需求

```python
# 消费贷: 受收入与信用约束限制
# 房贷: 受 LTV 上限 + DTI 上限 + 收入验证
# 信贷需求 = f(购房意愿, 消费缺口, 抵押品价值, 利率水平)
```

#### 5. 资产配置

```python
# 基于 mean-variance 框架的简化版
# 风险偏好 + 财富水平 → 股票/房产/储蓄分布
# Brock-Hommes 信念影响股票交易决策（见 MARKETS.md Section 4.4）
```

### 3.2.3 异质性来源

| 参数 | 分布 | 理由 |
|---|---|---|
| 初始教育 | Normal(0.5, 0.15) | 大多数人中等教育 |
| 初始财富 | LogNormal(μ=10, σ=1.5) | 右偏 → 帕累托尾 |
| 储蓄率 | Beta(2, 5) | 多数人低储蓄，少数高储蓄 |
| MPC | Beta(3, 3) | 集中在 0.5 附近 |
| 风险偏好 | TruncatedCauchy(0.5, 0.2, 0, 1) | 厚尾 → 少数极端风险偏好 |

---

## 3.3 Firms（企业）

**类型**：6 个部门（资本品 / 消费品 / 原材料 / 能源 / 住房 / 服务 / 高科技）。
MVP 用 3 个部门（消费品 / 资本品 / 服务）。

### 3.3.1 状态字段

```python
@dataclass
class Firm:
    id: str
    sector: str

    # ── 生产 ──
    capital: float
    productivity: float       # A, 部门异质
    tech_level: float         # 行业前沿
    energy_efficiency: float

    # ── 财务 ──
    cash: float
    deposits: float           # 银行存款
    revenues: float
    costs: float
    debt: float
    equity: float             # 净资产
    leverage: float           # debt / equity
    interest_coverage: float  # EBIT / interest_expense（偿债能力指标）

    # ── 运营 ──
    employees: int
    inventory: float
    price: float
    order_book: float
    capacity_utilization: float

    # ── 信用 ──
    credit_history: float     # 0–1 信用评分
    months_since_default: int # 距上次违约的月数
    is_bankrupt: bool
```

### 3.3.2 行为规则

#### 1. 生产决策

```python
# 基于订单 + 库存 + 产能利用率
# CES 生产函数（见 Section 3.12）
# Y = A * (α_K * K^ρ + α_L * L^ρ + α_E * E^ρ + α_M * M^ρ)^(1/ρ)
```

#### 2. 价格决策

```python
# Markup over marginal cost
# 粘性定价: 卡尔沃模型，每期只有 (1-θ) 概率调价
# 调价时: p_new = (1 + markup) * marginal_cost
# 未调价: p = p_prev * (1 + indexation * inflation)
```

#### 3. 雇佣决策

```python
# 基于预期需求 + 当前产能利用率
# labor_demand = f(expected_demand, capital_stock, tech_level)
# 雇佣/解雇有调整成本（招聘成本、遣散费）
```

#### 4. 投资决策

```python
# 托宾 Q: q = market_value / replacement_cost
# q > 1 → 扩张投资
# q < 1 → 收缩投资
# 受信贷可得性约束（金融加速器通道）
```

#### 5. 融资决策

```python
# 优先级: 内部融资 > 银行贷款 > 债券发行 > 股权发行
# 融资选择取决于: 资本成本, 信贷可得性, 市场条件
```

### 3.3.3 资本折旧 🆕

⚠️ **没有折旧就没有投资的稳态——资本只会单调增长。**

```python
# 每月执行
DEPRECIATION_RATES = {
    'capital_goods':   0.08,   # 年化 8%（机器设备磨损快）
    'consumer_goods':  0.06,   # 年化 6%
    'raw_materials':   0.07,   # 年化 7%
    'energy':          0.05,   # 年化 5%（能源基础设施寿命长）
    'housing':         0.02,   # 年化 2%（建筑折旧慢）
    'services':        0.10,   # 年化 10%（软件/知识贬值快）
    'high_tech':       0.15,   # 年化 15%（技术迭代快）
}

def apply_depreciation(firm: Firm, months: int = 1):
    annual_rate = DEPRECIATION_RATES[firm.sector]
    monthly_rate = annual_rate / 12
    firm.capital *= (1 - monthly_rate) ** months
```

折旧是投资的「稳态锚」——投资必须覆盖折旧才能维持资本存量。GDP 核算中：

```
净投资 = 总投资 - 折旧
资本存量 K(t+1) = K(t) × (1 - δ) + I_gross
```

---

## 3.4 Commercial Banks（商业银行）

### 3.4.1 状态字段

```python
@dataclass
class CommercialBank:
    id: str
    tier: int                  # 1 = 核心银行, 2 = 边缘银行

    # ── 资产 ──
    reserves: float           # 在 CB 的准备金
    loans: float              # 对 households/firms 的贷款
    securities: float         # 持有的政府债券
    interbank_claims: float   # 同业拆出

    # ── 负债 ──
    deposits: float           # 存款（核心负债）
    interbank_debt: float     # 同业拆入
    bond_issuance: float

    # ── 资本与风险 ──
    capital: float
    car: float                # 资本充足率
    npl_ratio: float          # 不良贷款率
    liquidity_ratio: float
    lcr: float                # 流动性覆盖率
    nsfr: float               # 净稳定资金比率

    # ── 运营 ──
    net_interest_income: float  # 净利息收入
    operating_cost: float       # 运营成本
    profit: float               # 税前利润
    dividend_payout_ratio: float  # 派息比率
    is_failed: bool
```

### 3.4.2 利率定价 🆕

⚠️ **政策利率如何传导到贷款利率是货币政策的生命线。**

```python
def bank_rate_setting(bank: CommercialBank, state: 'SimulationState'):
    """
    银行利率定价: 政策利率 → 存/贷款利率
    传导通道: 政策利率 + 银行利差 + 借款人风险溢价
    """
    policy_rate = state.cb.policy_rate

    # ─── 存款利率 ───
    # 跟随政策利率，但有下限 0（零利率下限）
    DEPOSIT_SPREAD = 0.015   # 存款利差 1.5%
    bank.deposit_rate = max(0, policy_rate - DEPOSIT_SPREAD)

    # ─── 基准贷款利率 ───
    CREDIT_SPREAD = 0.025     # 基础信贷利差 2.5%
    bank.base_lending_rate = policy_rate + CREDIT_SPREAD

    # ─── 借款人特定利率 ───
    # 在 base_lending_rate 之上加风险溢价
    def loan_rate_for(borrower) -> float:
        risk_premium = (
            0.3 * (1 - borrower.credit_score)         # 信用评分
          + 0.3 * (borrower.debt_to_income - 0.3)       # DTI 超标
          + 0.2 * (borrower.leverage - 1.0)             # 杠杆
          + 0.2 * max(0, borrower.npl_history)          # 违约历史
        )
        risk_premium = max(0, risk_premium)
        return bank.base_lending_rate + risk_premium

    # ─── 顺周期性（关键！）───
    # 丰年: 银行 CAR 充裕 → 竞争压低利差 → 信贷扩张
    # 荒年: 银行 CAR 不足 → 加大利差 → 信贷紧缩
    if bank.car > 0.12:  # 远超监管要求
        bank.base_lending_rate -= 0.005  # 让利抢客户
    elif bank.car < 0.08:  # 逼近监管红线
        bank.base_lending_rate += 0.01   # 风险溢价
```

### 3.4.3 利润与资本循环 🆕

⚠️ **银行的顺周期利润是信贷周期的核心放大器。**

```python
def bank_profit_cycle(bank: CommercialBank, state: 'SimulationState'):
    """
    银行利润 → 资本积累 → 放贷能力 → 信贷周期
    这是金融加速器的银行端通道
    """
    # ─── 1. 收入端 ───
    interest_income = (
        bank.loans * bank.avg_lending_rate
      + bank.securities * state.bond_yield
      + bank.interbank_claims * state.interbank_rate
    )
    interest_expense = (
        bank.deposits * bank.deposit_rate
      + bank.interbank_debt * state.interbank_rate
    )
    bank.net_interest_income = interest_income - interest_expense

    # ─── 2. 成本端 ───
    bank.operating_cost = (
        0.003 * bank.total_assets  # 运营成本约占总资产 0.3%
      + npl_provision(bank)         # 不良贷款拨备
    )

    # ─── 3. 利润 ───
    bank.profit = bank.net_interest_income - bank.operating_cost

    # ─── 4. 利润分配 ───
    if bank.profit > 0:
        # 留存 vs 派息: 资本充足时多派息,不足时全留存
        if bank.car > 0.10:
            dividend = bank.profit * bank.dividend_payout_ratio  # 通常 30-50%
            retained = bank.profit - dividend
        else:
            dividend = 0
            retained = bank.profit  # 全部留存补资本
    else:
        dividend = 0
        retained = bank.profit  # 亏损直接侵蚀资本

    # ─── 5. 资本更新 ───
    bank.capital += retained
    bank.car = bank.capital / bank.rwa  # 重新计算 CAR
```

**顺周期机制**：
```
经济繁荣 → 企业盈利好 → 银行 NPL 低 → 利润高 → 资本充足
  → 放贷标准放松 → 信贷扩张 → 资产价格上涨 → 进一步繁荣
  
经济衰退 → 企业违约 → 银行 NPL 升 → 利润降/亏损 → 资本侵蚀
  → 放贷标准收紧 → 信贷紧缩 → 资产价格下跌 → 进一步衰退
```

### 3.4.4 其他行为规则

1. **贷款评估**：借款人的现金流 + 抵押品 + 杠杆率 + 信用记录 → 是否放贷，利率多少
2. **同业拆借**：流动性管理，LCR/NSFR 约束下的最优拆借量
3. **资产组合**：贷款 / 证券 / 准备金的最优配比（受监管约束）
4. **最后贷款人申请**：CAR < 4% 或 LCR < 80% 时可向 CB 申请紧急流动性

### 3.4.5 银行失败规则

```
CAR ≥ 8%   → 正常运营
CAR < 8%   → 触发监管审查
CAR < 4%   → 触发早期干预（限制派息、要求增资计划）
CAR < 2%   → 触发重组或破产程序（见 Section 3.10）

LCR < 100% → 流动性警告
LCR < 80%  → 触发流动性紧急管理
```

---

## 3.5 Investment Banks（投资银行）

核心业务：**自营交易 + 承销 + 做市**。Phase 2 实现。

```python
@dataclass
class InvestmentBank:
    id: str

    capital: float
    var: float                # 风险价值 (Value-at-Risk)
    leverage: float           # 通常远高于商业银行（10-30x）

    trading_book: dict[str, float]  # 各资产持仓
    underwriting_pipeline: float

    funding: dict             # 短期融资构成
    is_failed: bool
```

**关键差异**（vs 商业银行）：
- 无存款业务，资金来源以短期回购为主
- 杠杆远高（受较少约束）
- 自营交易占比大 → 资产价格波动直接冲击资本
- 做市义务 → 市场流动性提供者，但危机时可能撤出

---

## 3.6 Asset Funds / Insurance（资管/保险）

**核心**：代理人业务 + 投资组合管理。Phase 2 实现。

```python
@dataclass
class AssetFund:
    id: str
    fund_type: str           # 'pension', 'insurance', 'mutual', 'hedge'
    aum: float                # 管理资产规模

    allocation: dict[str, float]  # 资产配置权重
    performance: float        # 过去表现
    flows: float              # 净流入/流出
    redemption_pressure: float  # 赎回压力（危机时飙升）
```

**信念机制**采用 Brock-Hommes（详见 [MARKETS.md](MARKETS.md) Section 5.1）。

**资管赎回螺旋**（Phase 2 重点）：
```
资产价格下跌 → 基金净值下降 → 投资者赎回 → 基金被迫卖出资产
  → 价格进一步下跌 → 更多赎回 → 恶性循环
```

---

## 3.7 Central Bank（中央银行）

```python
@dataclass
class CentralBank:
    policy_rate: float
    target_inflation: float    # 通胀目标
    neutral_rate: float        # 中性利率
    reserve_requirement: float # 存款准备金率
    countercyclical_buffer: float  # 逆周期资本缓冲

    # 资产负债表
    government_bonds: float    # 持有国债（OMO）
    other_assets: float
    bank_reserves: float       # 银行准备金（负债）
    currency_issued: float     # 流通现金（负债）
    capital: float

    # 状态
    is_lolr_active: bool       # 最后贷款人是否激活
    lolr_rate: float           # 最后贷款人利率
    lolr_disbursed: float      # 已发放的紧急贷款
```

### 3.7.1 Taylor Rule（默认货币政策）

```python
def taylor_rule(cb: CentralBank, state: 'SimulationState') -> float:
    """
    Taylor Rule: 央行利率设定规则
    渐进调整避免过度反应
    """
    r_neutral = cb.neutral_rate     # 默认 2.0%
    pi_target = cb.target_inflation  # 默认 2.0%
    pi_pi = 1.5                     # 通胀权重
    pi_y = 0.5                      # 产出缺口权重

    output_gap = (state.real_gdp - state.potential_gdp) / state.potential_gdp
    inflation_gap = state.inflation_yoy - pi_target

    r_target = r_neutral + pi_pi * inflation_gap + pi_y * output_gap

    # 渐进调整（利率平滑）
    SMOOTHING = 0.85
    r_new = SMOOTHING * cb.policy_rate + (1 - SMOOTHING) * r_target

    # 零利率下限
    r_new = max(r_new, -0.005)  # 允许轻微负利率

    return r_new
```

### 3.7.2 政策工具优先级

| 优先级 | 工具 | 频率 | 说明 |
|---|---|---|---|
| 1 | 政策利率 | 每月 | Taylor Rule 或手动覆盖 |
| 2 | 公开市场操作（OMO） | 按需 | 买卖国债调节准备金 |
| 3 | 最后贷款人（LOLR） | 紧急 | 向危机银行提供流动性 |
| 4 | 存款准备金率 | 结构性 | 影响银行可贷空间 |
| 5 | 逆周期资本缓冲 | 结构性 | 影响银行 CAR 要求 |

### 3.7.3 公开市场操作（OMO）

```python
def open_market_operation(cb: CentralBank, state: 'SimulationState'):
    """
    OMO: CB 买卖国债，调节银行准备金，使短端利率贴近政策利率
    """
    # 计算目标准备金（基于准备金率）
    target_reserves = cb.reserve_requirement * total_deposits
    reserve_gap = target_reserves - state.total_bank_reserves

    if reserve_gap > 0:
        # 准备金不足 → CB 买入国债 → 注入准备金
        cb.buy_gov_bonds(amount=reserve_gap)
    elif reserve_gap < 0:
        # 准备金过多 → CB 卖出国债 → 吸收准备金
        cb.sell_gov_bonds(amount=-reserve_gap)
```

---

## 3.8 Government（政府）

```python
@dataclass
class Government:
    # 债务
    debt: float               # 总国债存量
    debt_to_gdp: float

    # 流量
    tax_revenue: float        # 总税收收入
    expenditures: float       # 总支出（含购买 + 转移支付）
    gov_spending: float       # 政府购买 G
    transfers: float          # 转移支付 TR（失业救济、养老金等）
    interest_payment: float   # 国债利息支出
    primary_balance: float    # 初级余额 = 税收 - 非利息支出
```

### 3.8.1 政府预算约束 🆕

```python
def government_budget_constraint(gov: Government, state: 'SimulationState'):
    """
    政府预算恒等式（每期必须满足）
    ΔB = G + TR + INT_gov - T
    """
    # 税收
    income_tax = sum(hh.income * TAX_RATE for hh in state.households)
    corporate_tax = sum(f.profit * CORP_TAX_RATE for f in state.firms if f.profit > 0)
    gov.tax_revenue = income_tax + corporate_tax

    # 利息支出
    gov.interest_payment = gov.debt * state.bond_yield

    # 初级余额
    gov.primary_balance = gov.tax_revenue - gov.gov_spending - gov.transfers

    # 赤字 → 发行国债
    deficit = gov.gov_spending + gov.transfers + gov.interest_payment - gov.tax_revenue
    if deficit > 0:
        # 发行新债融资
        new_bonds = deficit
        gov.debt += new_bonds
        # 新债由银行 + 家庭 + CB 购买
        allocate_new_bonds(new_bonds, state)
    else:
        # 盈余 → 偿还国债（可选）
        gov.debt += deficit  # deficit < 0 → 债务减少

    gov.debt_to_gdp = gov.debt / state.nominal_gdp
```

### 3.8.2 用户可控的政策工具

| 工具 | 默认 | 可调范围 | 影响 |
|---|---|---|---|
| 政府支出 G | 占 GDP 20% | 0% – 50% | 总需求 |
| 所得税率 | 25% | 0% – 50% | 家庭可支配收入 |
| 企业税率 | 21% | 0% – 40% | 企业投资激励 |
| 转移支付 TR | 自动稳定器 | 占 GDP 0% – 30% | 低收入家庭收入 |

---

## 3.9 Foreign Sector（外资）

**可选模块**。MVP 不实现。若启用：
- 出口/进口（贸易账户）
- 资本流入/流出（资本账户）
- 汇率（钉住 / 浮动 / 管理浮动）

```python
@dataclass
class ForeignSector:
    exports: float
    imports: float
    trade_balance: float     # X - M
    capital_flows: float     # 净资本流入
    fx_rate: float           # 汇率（本币/外币）
 fx_position: float         # 总外汇敞口
```

---

## 3.10 Default & Bankruptcy 🆕

⚠️ **没有违约就没有 NPL 上升，就没有银行资本侵蚀，就没有危机涌现。这是连接实体经济与金融部门的关键环节。**

### 3.10.1 企业违约

```python
FIRM_DEFAULT_TRIGGERS = {
    'cash_flow': 0,       # 现金流 < 0 且持续 3 个月
    'interest_coverage': 1.0,  # ICR < 1: 利息都还不起
    'equity_negative': 0,  # 净资产 < 0
}

def check_firm_default(firm: Firm, months_negative_cashflow: int) -> bool:
    """企业违约判定"""
    if firm.equity < 0:
        return True
    if firm.interest_coverage < 1.0 and months_negative_cashflow >= 3:
        return True
    if firm.cash < 0 and months_negative_cashflow >= 3:
        return True
    return False
```

### 3.10.2 家庭违约

```python
HH_DEFAULT_TRIGGERS = {
    'dti': 0.6,            # DTI > 60%（极端高杠杆）
    'unemployment': 12,    # 失业超过 12 个月
    'negative_equity': True,  # 房屋市值 < 房贷余额
}

def check_household_default(hh: Household, state: 'SimulationState') -> bool:
    """家庭违约判定（主要是房贷）"""
    # 负资产: 房价下跌导致抵押品价值 < 贷款余额
    if hh.housing_units > 0:
        housing_value = hh.housing_units * state.housing_price
        if housing_value < hh.mortgage_balance:
            # 负资产 + 失业 → 违约概率高
            if not hh.employed and hh.unemployment_duration > 6:
                return True
    return False
```

### 3.10.3 违约损失分配

```python
def resolve_firm_default(firm: Firm, state: 'SimulationState'):
    """
    企业违约后的损失分配
    核心原则: 资产清偿按优先级
    """
    # 1. 确定总资产和总负债
    total_assets = firm.cash + firm.deposits + firm.inventory + firm.capital
    total_liabilities = firm.debt + firm.accounts_payable

    if total_assets >= total_liabilities:
        # 资不抵债但资产足够 → 重组
        recovery_rate = total_assets / total_liabilities  # < 1
    else:
        # 资不抵债 → 破产清算
        recovery_rate = total_assets / total_liabilities  # 可能很低
        # 抵押品价值折价（流动性折扣 30-50%）

    # 2. 按优先级清偿
    # 优先级: 工资 > 税款 > 有担保贷款 > 无担保贷款 > 股权
    wage_claims = firm.employees * firm.wage * 2  # 2 个月工资优先
    tax_claims = firm.profit * CORP_TAX_RATE

    # 3. 银行损失
    for bank in firm creditor_banks:
        loss = bank.exposure_to(firm) * (1 - recovery_rate)
        bank.loans -= loss          # 贷款核销
        bank.capital -= loss        # 资本直接扣除
        bank.npl_ratio = update_npl(bank)

    # 4. 企业处置
    firm.is_bankrupt = True
    release_employees(firm, state)  # 工人失业
```

### 3.10.4 家庭违约处置

```python
def resolve_household_default(hh: Household, state: 'SimulationState'):
    """
    家庭房贷违约处置
    """
    # 1. 银行收回抵押品（房产）
    bank = hh.mortgage_lender
    bank.reo_properties += hh.housing_units  # REO: 不动产持有

    # 2. 银行核销损失
    mortgage_balance = hh.mortgage_balance
    collateral_value = hh.housing_units * state.housing_price * 0.7  # 清算折扣 30%
    loss = max(0, mortgage_balance - collateral_value)

    bank.loans -= mortgage_balance
    bank.capital -= loss
    hh.mortgage_balance = 0
    hh.housing_units = 0

    # 3. 家庭信用记录受损
    hh.credit_score = 0.1  # 严重受损
    hh.months_since_default = 0

    # 4. 银行持有 REO 的后续处理
    # 银行会在后续月份逐步出售 REO → 形成 fire-sale 压力（见 SIMULATION.md）
```

---

## 3.11 Demographics ❓

> 待讨论：是否在 MVP 中包含人口学动态？

长期模拟（100+ 年）需要：

- **人口增长/老化**：劳动力供给的慢变量
- **新家庭进入**：青年进入劳动力市场，形成新消费/信贷需求
- **退休/死亡**：资产出售（房产、股票）→ 价格压力
- **代际财富转移**：遗产税 + 遗赠 → 财富分布的代际传导

**建议**：MVP 使用静态人口（固定家庭数），Phase 3 加入简单的人口更替模型。

---

## 3.12 生产结构概要

> CES 生产函数与部门参数见上方 Section 3.3。

6 个部门 + CES 生产函数：

```
Y_i = A_i · (α_K · K^ρ + α_L · L^ρ + α_E · E^ρ + α_M · M^ρ)^(1/ρ)
```

部门 TFP 增长率（年化，季度更新）：

| 部门 | TFP 增长 | 折旧率 | 替代弹性 σ |
|---|---|---|---|
| 资本品 | 1–2% | 8% | 0.5 |
| 消费品 | 1–2% | 6% | 0.7 |
| 原材料 | 0.5–1% | 7% | 0.4 |
| 能源 | 0.5–1.5% | 5% | 0.3 |
| 住房 | 0.5–1% | 2% | 0.6 |
| 服务 | 1–2% | 10% | 0.8 |
| 高科技 | 5–10% | 15% | 0.9 |
