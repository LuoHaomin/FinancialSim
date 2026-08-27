# 货币与金融架构

> 返回：[DESIGN.md](../DESIGN.md)
> 版本：v0.2 | 2026-08-27

---

## 5.1 混合型货币架构

**核心断言**：现代货币体系同时具有外生与内生特征。

| 特征 | 主体 | 机制 |
|---|---|---|
| 外生 | 中央银行 | 控制基础货币（准备金 + 流通现金）和政策利率 |
| 内生 | 商业银行 | 通过贷款创造存款（广义货币） |

**政策传导双渠道**：
1. **利率渠道**：政策利率 → 市场利率 → 借贷成本 → 投资消费
2. **信贷条件渠道**：政策利率 → 银行资本/流动性 → 信贷标准 → 信贷量

### 货币创造流程

```
1. CB 设政策利率 r
   ↓
2. 家庭/企业向商业银行申请贷款
   ↓
3. 商业银行评估后放贷（同时创造存款）
   ↓
4. 借款人支出 → 存款转移到收款方账户
   ↓
5. 银行间清算 → 准备金流动
   ↓
6. CB 通过 OMO 调节准备金供给，使短端利率贴近政策利率
```

### 关键概念

- **M0**（基础货币）= 流通现金 + 银行准备金
- **M2**（广义货币）= M0 + 活期存款 + 定期存款
- **货币乘数**：教科书定义 `M2/M0`；现代实际是"内生货币供给"——贷款在前，乘数在后
- **存款创造**：贷款 = 资产增加 = 负债增加（同时发生，不是"存款变贷款"）

---

## 5.2 银行体系

### 5.2.1 双层结构

| 层级 | 类型 | 特征 | 约束 |
|---|---|---|---|
| 上层 | 商业银行 | 存贷业务，杠杆 10-15x | CAR, LCR, NSFR, 准备金率 |
| 上层 | 投资银行 | 自营交易，杠杆 15-30x | VaR 限制，较少监管 |
| 下层 | 中央银行 | 最后贷款人，货币政策 | 无盈利约束 |

### 5.2.2 银行失败阈值

```
CAR ≥ 8%   → 正常运营
CAR < 8%   → 触发监管审查
CAR < 4%   → 触发早期干预（限制派息、要求增资计划）
CAR < 2%   → 触发重组或破产（见 AGENTS.md Section 3.10）

LCR < 100% → 流动性警告
LCR < 80%  → 触发流动性紧急管理
```

---

## 5.3 Stock-Flow Consistency（SFC 会计内核）

⚠️ **这是模型的物理定律。所有交易必须满足会计恒等式——不是可选优化，是地基。**

### 5.3.1 五大部门资产负债表（独立类）🆕

> v0.2 修正：将原来的单体 `SectorBalanceSheet` 拆分为 5 个独立类，
> 每个部门有各自特定的资产负债结构。

```python
from __future__ import annotations
from dataclasses import dataclass, field


class BalanceSheetProtocol:
    """所有部门资产负债表必须实现的接口"""
    def sum_assets(self) -> float: ...
    def sum_liabilities(self) -> float: ...
    @property
    def net_worth(self) -> float: ...


@dataclass
class HouseholdBalanceSheet:
    """家庭部门资产负债表"""
    # 资产
    cash: float = 0.0
    deposits: float = 0.0          # 银行存款
    stocks: float = 0.0            # 股票市值
    bonds: float = 0.0             # 债券市值
    housing_self: float = 0.0      # 自住房（按市价）
    housing_investment: float = 0.0  # 投资性房产
    consumer_durables: float = 0.0
    # 负债
    mortgage: float = 0.0          # 房贷
    consumer_loan: float = 0.0     # 消费贷
    other_debt: float = 0.0

    def sum_assets(self) -> float:
        return (self.cash + self.deposits + self.stocks + self.bonds
              + self.housing_self + self.housing_investment
              + self.consumer_durables)

    def sum_liabilities(self) -> float:
        return self.mortgage + self.consumer_loan + self.other_debt

    @property
    def net_worth(self) -> float:
        return self.sum_assets() - self.sum_liabilities()


@dataclass
class FirmBalanceSheet:
    """企业部门资产负债表"""
    # 资产
    cash: float = 0.0
    deposits: float = 0.0          # 银行存款
    inventories: float = 0.0
    capital_stock: float = 0.0     # 实物资本（按历史成本或重置成本）
    interfirm_claims: float = 0.0  # 应收账款
    # 负债
    bank_loans: float = 0.0        # 银行贷款
    bonds_issued: float = 0.0      # 公司债
    accounts_payable: float = 0.0  # 应付账款

    def sum_assets(self) -> float:
        return (self.cash + self.deposits + self.inventories
              + self.capital_stock + self.interfirm_claims)

    def sum_liabilities(self) -> float:
        return self.bank_loans + self.bonds_issued + self.accounts_payable

    @property
    def net_worth(self) -> float:
        return self.sum_assets() - self.sum_liabilities()


@dataclass
class CommercialBankBalanceSheet:
    """商业银行部门资产负债表（聚合）"""
    # 资产
    reserves: float = 0.0          # 在 CB 的准备金
    loans_to_firms: float = 0.0
    loans_to_households: float = 0.0
    gov_bonds_held: float = 0.0    # 持有国债
    interbank_claims: float = 0.0  # 同业拆出
    # 负债
    deposits_from_hh: float = 0.0  # 家庭存款
    deposits_from_firms: float = 0.0  # 企业存款
    interbank_debt: float = 0.0    # 同业拆入
    bonds_issued: float = 0.0      # 银行债
    # 资本
    capital: float = 0.0

    def sum_assets(self) -> float:
        return (self.reserves + self.loans_to_firms + self.loans_to_households
              + self.gov_bonds_held + self.interbank_claims)

    def sum_liabilities(self) -> float:
        return (self.deposits_from_hh + self.deposits_from_firms
              + self.interbank_debt + self.bonds_issued)

    @property
    def net_worth(self) -> float:
        return self.capital  # 银行的 NW = 资本


@dataclass
class GovernmentBalanceSheet:
    """政府部门资产负债表"""
    # 资产
    treasury_deposits: float = 0.0  # 在央行的国库存款
    other_assets: float = 0.0
    # 负债
    bonds_outstanding: float = 0.0  # 总国债

    def sum_assets(self) -> float:
        return self.treasury_deposits + self.other_assets

    def sum_liabilities(self) -> float:
        return self.bonds_outstanding

    @property
    def net_worth(self) -> float:
        return self.sum_assets() - self.sum_liabilities()  # 通常为负


@dataclass
class CentralBankBalanceSheet:
    """中央银行资产负债表"""
    # 资产
    gov_bonds: float = 0.0          # 持有国债（OMO）
    lolr_claims: float = 0.0       # 最后贷款人贷款
    other_assets: float = 0.0
    # 负债
    bank_reserves: float = 0.0     # 银行准备金
    currency_issued: float = 0.0   # 流通现金
    # 资本
    capital: float = 0.0

    def sum_assets(self) -> float:
        return self.gov_bonds + self.lolr_claims + self.other_assets

    def sum_liabilities(self) -> float:
        return self.bank_reserves + self.currency_issued

    @property
    def net_worth(self) -> float:
        return self.capital
```

### 5.3.2 流量矩阵（Transaction Flow Matrix）

```python
# 所有交易双重记账: 付款方 -X, 收款方 +X
# 每一行流量有确定的源部门和目标部门

TRANSACTION_MATRIX = {
    # ─── 实体经济 ───
    ('households', 'firms',        'consumption_C'):  ...,  # 消费
    ('firms',      'households',   'wages_W'):        ...,  # 工资
    ('firms',      'households',   'dividends_DIV'):  ...,  # 股息
    ('firms',      'firms',        'investment_I'):   ...,  # 投资品交易
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
    ('households', 'households',   'stock_trade'):    ...,  # 内部, 净额为 0
    ('households', 'firms',        'stock_issuance'): ...,  # IPO/增发的净额

    # ─── 外资 (预留桩) ───
    ('firms',      'foreign',      'exports_X'):      ...,
    ('foreign',    'firms',        'imports_M'):      ...,
    ('households', 'foreign',      'fx_position'):    ...,
    ('firms',      'foreign',      'fdi'):            ...,
}
```

### 5.3.3 守恒校验（每 tick 强制执行）🆕

```python
EPSILON = 1e-6  # 浮点容差


def validate_sfc(state: 'SimulationState') -> list[str]:
    """
    每个 tick 结束调用。违反则返回错误列表。
    校验 6 项守恒约束。
    """
    errors = []
    bs = state.balance_sheets  # 5 个部门的资产负债表

    # ─── 1. 资产负债表恒等式: A = L + NW ───
    for name, sheet in bs.items():
        total_a = sheet.sum_assets()
        total_l = sheet.sum_liabilities()
        nw = sheet.net_worth
        if abs(total_a - total_l - nw) > EPSILON:
            errors.append(
                f"BS violation: {name} A={total_a:.2f} L={total_l:.2f} NW={nw:.2f}"
            )

    # ─── 2. 部门净借贷之和 = 0 (封闭系统) ───
    total_nl = (
        bs['households'].net_lending
      + bs['firms'].net_lending
      + bs['government'].net_lending
      + bs['banks'].net_lending
      + bs['cb'].net_lending  # 按 SFC 定义 = 0
    )
    if state.foreign_enabled:
        total_nl += state.foreign.net_lending
    if abs(total_nl) > EPSILON:
        errors.append(f"Net lending violation: sum = {total_nl:.6f}")

    # ─── 3. 货币守恒 🆕 修正: 加入企业存款 ───
    # 货币供给 = 家庭存款 + 企业存款 + 流通现金
    money_supply = (
        bs['households'].deposits
      + bs['firms'].deposits
      + bs['cb'].currency_issued
    )
    # 货币使用 = 银行资产端的对应项
    money_uses = (
        bs['banks'].loans_to_firms
      + bs['banks'].loans_to_households
      + bs['banks'].gov_bonds_held
      + bs['banks'].reserves
    )
    if abs(money_supply - money_uses) > EPSILON:
        errors.append(
            f"Money conservation: supply={money_supply:.2f} uses={money_uses:.2f}"
        )

    # ─── 4. 央行资产负债表平衡 ───
    cb_a = bs['cb'].sum_assets()
    cb_l = bs['cb'].sum_liabilities() + bs['cb'].capital
    if abs(cb_a - cb_l) > EPSILON:
        errors.append(f"CB BS violation: A={cb_a:.2f} L+K={cb_l:.2f}")

    # ─── 5. 政府债务恒等式 ───
    # ΔDebt = G + TR + INT_gov - T（每期流量）
    # 由政府模块自己保证

    # ─── 6. 净值变动 = 储蓄 + 资本利得 ───
    for name, sheet in bs.items():
        if name == 'cb':
            continue  # 央行利润回流政府，单独处理
        saving = (sheet.income - sheet.expenditure
                  + sum(sheet.transfers_in) - sum(sheet.taxes_paid))
        capgain = sheet.capital_gains_period
        expected_dnw = saving + capgain
        actual_dnw = sheet.net_worth - sheet.prev_net_worth
        if abs(expected_dnw - actual_dnw) > EPSILON:
            errors.append(
                f"NW change violation: {name} expected={expected_dnw:.4f} "
                f"actual={actual_dnw:.4f}"
            )

    return errors
```

**v0.1 → v0.2 修正**：
- ❌ 旧版 `SectorBalanceSheet` 将 5 个部门混在一个类 → ✅ 拆为 5 个独立类
- ❌ 旧版货币守恒等式遗漏企业存款 → ✅ 加入 `bs['firms'].deposits`
- ❌ 旧版用 `assert` 直接中断 → ✅ 改为返回错误列表，支持更灵活的处理

### 5.3.4 SFC 校验的集成位置

```python
# core/state.py
class SimulationState:
    def end_tick(self):
        errors = validate_sfc(self)
        if errors:
            logger.critical(f"SFC violations at tick {self.t}:")
            for e in errors:
                logger.critical(f"  {e}")
            self.snapshot("sfc_violation")
            raise SFCViolation(errors)


class SFCViolation(Exception):
    """违反 SFC 约束时抛出。"""
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"{len(errors)} SFC violation(s)")
```

### 5.3.5 部门净借贷恒等式

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

### 5.3.6 资本利得的处理

**资本利得不创造货币**——它是**存量重估**：

```
家庭持股 1000 股 @ $10 → 市值 $10,000
股价涨到 $12 → 市值 $12,000
家庭 wealth += $2,000 (资本利得)
但任何人都没有额外 "$2,000"——是从其他持有人那里转移过来的
```

实现：每次资产价格变动，**所有持有者的财富总和不变**（零和），但**分布变化**（赢家与输家）。

---

## 5.4 利率传导完整通道 🆕

> 银行端定价见 AGENTS.md Section 3.4.2。此处描述完整传导链。

```
政策利率 (CB)
    │
    ├──→ 同业拆借利率（隔夜）
    │       │
    │       ├──→ 银行存款利率（存款端）
    │       └──→ 银行基准贷款利率（贷款端）
    │              │
    │              └──→ 借款人特定利率
    │                     = 基准利率 + 信用风险溢价
    │
    ├──→ 债券市场短期利率
    │       │
    │       └──→ 期限结构 → 长期债券利率
    │
    └──→ 资产市场贴现率
           │
           └──→ 股票/房产估值
```

**传导时滞（教学关键）**：

| 环节 | 时滞 | 原因 |
|---|---|---|
| 政策利率 → 同业利率 | 即时 | OMO 操作直接调节 |
| 同业利率 → 贷款利率 | 1-3 月 | 贷款合同重定价周期 |
| 贷款利率 → 企业投资 | 3-6 月 | 投资决策周期 |
| 贷款利率 → 家庭消费 | 6-12 月 | 消费习惯调整 + 固定利率合约 |
| 利率 → 资产价格 | 即时-1 月 | 金融市场反应快 |
| 资产价格 → 财富效应 → 消费 | 3-12 月 | 心理账户 + 流动性约束 |