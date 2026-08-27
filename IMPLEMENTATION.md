# ABM 宏观经济仿真器：实现计划

> 状态：Phase 0 ✅ / Phase 1 ✅ / Phase 2 ✅ / Phase 3 前置 ✅ / Week A ✅ / Week B ✅ / **Week C M1+M2 ✅ (BH 股市 + 组合选择 + 波动聚集校准)**
> 最后更新：2026-08-27
> 对应设计：[DESIGN.md](DESIGN.md) + [docs/](docs/)

---

## 进度看板（2026-08-27 更新）

**测试基线**: 279 passed · 1 xfail · ruff clean · 全部场景零 SFC 违反

### Phase 3 Week C 里程碑 2: 组合选择 + 波动聚集校准（2026-08-27 完成）

| 项 | 状态 | 说明 |
|---|---|---|
| **C-M2a risk_tolerance** | ✅ | 家庭风险偏好 ∈[0,1] 截断正态初始化；目标股票权重 w*=0.05+0.40×tol，20%/月向目标迁移 |
| **C-M2b 过户语义** | ✅ | 再平衡按"家庭间等额配对成交"实现: 总股数守恒、聚合存款不动（否则凭空增减持仓破坏供给守恒） |
| **C-M2c 波动聚集** | ✅ | 子步 4→12 (日级近似): \|r_t\| 自相关均值 0.31 > 0.1 (三种子)，年化波动 ~30% |
| **Q9 性能实测** | ✅ | n=300 股市全开 ~7ms/tick，测试上限 250ms |

横截面验收: 高 tolerance 四分位的实际股票权重系统性高于低四分位。

### Phase 3 Week C 里程碑 1: Brock-Hommes 股票市场（2026-08-27 完成）

| 项 | 状态 | 说明 |
|---|---|---|
| **C-1 BH 引擎** | ✅ | `markets/stocks.py`: 7 条信念规则 + Trader + 做市商出清; 子步循环近似日级 (`stock_substeps_per_month=4`, Q9 性能阀) |
| **C-2 IPO + 持仓** | ✅ | 企业发行 `shares_outstanding`; 家庭按存款比例认购; 票面价锚 (账面权益≤0 时 `stock_par_price`) |
| **C-3 分红锚定** | ✅ | `_firm_dividend_cycle` 改按持股分配 → R2 基本面规则有真实股息锚 (`state.last_month_dividends`) |
| **C-4 SFC 结算** | ✅ | 二级市场只在家庭部门内部轧平: 只结算净流 (deposit↔units 镜像), 估值重估不入账 |
| 快照 v4 | ✅ | stock_market 序列化含 Trader fitness ndarray |

**关键设计取舍** (记录避免重蹈):
1. **fitness 从"预测误差"改为"虚拟盈亏"**: 原版只给被选用规则记 −|偏差|,
   远离价格的基本面规则永远得不到正反馈 → 市场无锚. 虚拟 P&L
   (`score_k = sign(pred_k−p_old)×r`) 让系统性低估时的买入信号持续积累,
   价值发现通道才能打开.
2. **微观数量级需实证标定**: 订单尺寸/深度/λ 的初值差了两个数量级 (价格钉死),
   直接网格搜索定标: λ=0.40, depth=10, order_fraction=0.15
   → 年化波动 ~12%, kurtosis 3.2-3.4 (>3 厚尾 ✓), 价格向基本面缓慢收敛.

**Week C 验收实测**: enable_stock_market=True 三种子 48 月:
零 SFC 违反; 持仓守恒 = 总股数; Σhh.deposits 与银行镜像逐位一致;
厚尾 kurtosis≥3; 同种子逐位复现; 快照 v4 roundtrip.

**Week C 后续里程碑** (留待继续): 交叉持股骨架 (Scale-Free 图);
i-bank/资管接入为股市对手方 (Week D).

### Phase 3 Week B: 劳动市场跨部门流动 + 失业深化（2026-08-27 完成）

| 项 | 状态 | 说明 |
|---|---|---|
| **B-1 动态劳动需求** | ✅ | `_update_labor_demand`: 目标就业 L*=滞后需求/(A·P)，上下不对称调整 (扩员25%/月、裁员35%/月)；目标下调立即裁员入失业池 |
| **B-2 疤痕效应** | ✅ | 长期失业 >6 月后每超 1 月再就业工资折扣 1%，封顶 30%；`_scar_discounted_wage` |
| **B-3 部门份额自洽化** | ✅ | demand_share 与 labor_share 成比例 — 此前 energy (5%/10%) 结构性亏损两个月破产级联 |
| **G 实物流** | ✅ | 政府购买改为真实市场采购: 抽库存+计入销售额，未成交不付款 |
| **幻影购买修复** | ✅ | 库存不足时不成交部分退回家中存款；未成交需求记 `firm.last_demand` 作为招聘扩张信号 |

**Week B 关键诊断链** (值得记取的建模教训):
1. 固定价值份额需求下, "少雇人→供给不足→销售额缩→更少雇人" 死循环 → 多部门 u≈25%。
2. 加入动态劳动需求后更糟 (单部门 24 月 u→85%): 销售基数只有家庭消费 (mpc(1−τ)<1),
   **G 凭空注资不入销售账**是塌缩根因 → G 实物流修复。
3. 仍塌缩: 家庭为无货商品付钱 (幻影购买) 且未成交需求不可见 → 限量成交+退款+
   `last_demand` 记账, 失业归零。
4. baseline 因此变成完美稳态 (u≡0) — 奥肯定律改在深度紧缩场景检验。

**Week B 验收实测**: 多部门 + 两轮 55% 深度紧缩, 六个种子全部:
峰值失业 ~0.8 → 尾段回落 ~0.003 (恢复充分就业), 全程零 SFC 违反。
旧 Okun xfail (`test_minsky_peak_unemployment`) 在 Week B 动态下已可 XPASS
(seed 42), 但跨种子不稳定 (7/99 peak≈0.005), 保留 loose xfail 标注。

### Phase 3 Week A: 多部门 + 资本品闭环（2026-08-27 完成）

| 项 | 状态 | 说明 |
|---|---|---|
| **A-1 多企业列表化** | ✅ | `state.firms: list[Firm]`，`state.firm` 为 `firms[0]` 别名 property；默认单部门行为与 Phase 2 逐位一致 |
| **A-2 部门参数表** | ✅ | `config.SECTOR_DEFAULTS`: consumer/capital/energy/housing_services/high_tech/services 六部门的劳动份额+需求份额+TFP；`normalized_labor_shares()` / `normalized_demand_shares()` |
| **A-3 CES 生产函数** | ✅ | `Firm.production_function="ces"`: Y=A·(αK^ρ+(1−α)L^ρ)^(1/ρ)，σ=1 走 Cobb-Douglas 守护；7 个数值单测。默认仍 linear |
| **A-4 投资实流化** | ✅ | 企业投资向资本品部门真实采购: 买方 deposits−V/capital+V ↔ 卖方 inventory−V/deposits+V，受资本品库存约束；无资本品部门时回退 legacy 实物化路径 |
| **A-5 编排多企业化** | ✅ | labor(按雇主归属离职/跨企业空缺分配雇佣)、wages、消费需求分流、银行利息/公司税/G 分配、违约处置逐企业执行 |
| **A-6 快照 v3** | ✅ | 序列化 `firms` 列表，续跑可复现 |

**Week A 过程中发现并修复的记账 bug**:
- **破产清算存款幽灵**: `declare_bankruptcy` 把清算回收 R 直接记入 firm.deposits
  却无银行对手方 → 每次破产 Δ≈R 的存款失配（多部门场景放大触发）。
  修复: 新增 `bank.seized_assets` 科目接收等额清算资产
  （`seized_assets↑R / deposits_from_firms↑R`, A=L+cap 保持），SFC 校验扩项同步。

**遗留（进 Week B/后续）**:
- 多部门摩擦失业再平衡偏慢（baseline 失业率 ~10-20%），需 Week B 失业池 +
  部门再配置机制深化; 当前验收以零 SFC 违反为准
- CES 未默认启用: 打开后企业对价格的反应会改变 baseline 校准, 留待稳态
  重校准时一并切换 (§4.1 稳态修复)
- 中间品 IO 矩阵顺延至 Week A 后半段/Week E (供应链网络), 见 §5

### Phase 3 前置批次 P0-a / P0-b / P0-c（2026-08-27 完成）

| 项 | 状态 | 说明 |
|---|---|---|
| **P0-a 消费信贷** | ✅ 脚手架 | `markets/credit.py` + `ConsumerCreditMarket` + `_consumer_credit_cycle` step 函数。DTI 配给规则 + 等额本息还款. `enable_consumer_credit=False` 默认关闭 (验证通过SFC + 字段齐, 待 Phase 3 完整调) |
| **P0-b 债券市场** | ⚠️ 脚手架, 默认关闭 | `markets/bonds.py` + `_bond_cycle` step 函数. 默认 `enable_bond_market=False` — 内部记账有未解的舍入残差, 不能安全地默认开启. 详见限制清单 #4. |
| **P0-c 场景库** | ✅ 完整 | 4 个 YAML (`baseline`, `crisis_2008`, `tight_credit`, `loose_credit`) + `scenarios.load_scenario()` 加载器 + 8 个单测. |

### 修复与 SFC 扩项（2026-08-27 一次刷）

1. **REO 修复**: 旧版 `write_off_mortgage` 全额 + `h.housing_units = 0` → 房子人间蒸发. 现以清算折扣 (70%) 回收, 入 `bank.reo_value`, 房屋所有权转移给银行 (`bank.reo_properties`). 新增 ` `校验`  ` 6 项校验之 `validate_housing_stock`.
2. **SFC 校验扩项**: 1→6 项 (新增家庭负债 / 企业贷款 / 财政部存款 / 住房存量). 之前这些字段都从校验范围之外, 一侧漂移无人察觉.
3. **多银行初始化**: 移除 `creditor.capital += amount` 的不对称记账 (导致 ±2409 单位 BS 漂移). 主银行持有部门聚合资金流, 外围银行初始 reserves=0, **同业敞口挂起留给 Phase 3 Week E**.
4. **Rounding 残差**: 1000+ 家庭等比分摊 1e-3 量级数字时产生 <1e-9 累积误差. 现按"最后一人吃下残差"逻辑吸收进银行资本.
5. **卫生**: config 重复 `n_banks` → 移除; README 状态表 → 更新到 Phase 0-2 完成; 失效 xfail 标记 (`test_log_wealth_approximately_lognormal`) → 删除.

### Phase 0 — 全部完成 ✅
Day 1-14 计划项全部交付：脚手架、SFC 内核、5 个简化主体、月度 tick、商品/劳动市场、e2e + 性能测试。

### Phase 1 已完成（约 Week 3-7 核心部分）

| 模块 | 内容 | 文件 |
|---|---|---|
| RNGManager | 命名流、可复现、reset/spawn | `simulation/rng.py` |
| 异质性分布 | LogNormal 工资/存款, 截断正态储蓄率/MPC | `utils/distributions.py` |
| 配置扩展 | Taylor 参数/税率/财政/银行利差/CAR/折旧/卡尔沃/异质性参数 | `config.py` |
| 完整 Household | 永久收入消费 + 财富效应(λ 可配) + 流动性约束 | `agents/household.py` |
| 完整 Firm | 折旧 δ、加速器投资、卡尔沃定价(可选) | `agents/firm.py` |
| 完整 Bank | 政策利率传导存贷定价 + CAR 溢价顺周期 + 利润循环 | `agents/commercial_bank.py` |
| Government 预算 | 收入税/公司税/G/失业救济; 赤字经 CB 购债融资 | `core/step.py` `_government_cycle` |
| 通胀预期 | 适应性 + 锚回归 + 脱锚(persistence) | `expectations/inflation.py` |
| 快照/重放 | JSON 全量序列化 + 恢复后续跑 | `simulation/snapshot.py` |
| 测试 | +33 个: rng/预期/主体扩展/快照/复现性 | `tests/unit/test_{rng,inflation_expectation,phase1_agents,snapshot}.py` |

### 过程中发现并修复的关键问题

1. **贷款利息资本化破坏银行恒等式**: 企业付不起利息计入债务时，银行资产↑但没有按权责发生制确认收入 → 资本缺口。已修（资本化同时记 income）。
2. **商品市场定价时序**: 定价在补库存之前执行 → 库存永远"偏低"→ 月月提价 → 通胀螺旋脱锚。已修为月末库存定价。
3. **工资规则过激**: Phase 0 半年调薪系数 0.5 在充分就业下每半年加薪 50%。改为通胀指数化 + κ=0.10 的菲利普斯斜率。
4. **财政规模失配**: G 从固定金额改为潜在产出比例(45%)自动定标; 稳态校准 ≈ 1 − avg_mpc×(1−τ)。
5. **SFC 校验容差**: 绝对 1e-6 在 ~1e4 量级下浮点累积误差误报, 改为相对容差。

### Phase 2 已完成（金融层扩展）

| 模块 | 内容 | 文件 |
|---|---|---|
| 房产市场 | 租金锚定价 (cap rate) + 利率反馈 + 泡沫/恐慌因子 | `markets/housing.py` |
| 抵押贷款 | 初始组合发放、等额月供摊销、断供计数器 → NPL → REO | `core/step.py` `_housing_cycle` / `_mortgage_default_check` |
| 多家商业银行 | n_banks 可配, 主银行语义, Core-Periphery 同业敞口 | `core/simulation.py`, `network/interbank.py` |
| Fire-sale 外部性 | REO 甩卖按比例压低房价 → 更多负资产 → 违约螺旋 | `step._fire_sale_and_failure` |
| 银行失败处置 | CAR 阈值触发 → 同业传染 (recovery 40%) → 政府多轮救助注资 | `step._fire_sale_and_failure` |
| 危机场景 | 2008 型 preset（风险溢价飙升+紧缩）全链路涌现, SFC 全程干净 | `tests/integration/test_crisis.py` |

**危机涌现验证** (seed=7, n=300, 双重风险溢价飙升 + 财政紧缩 + 加息):
房价 120→~7 (−95%), 抵押核销发生, bank_1 失败, 同业传染, 政府 TARP 式多轮注资
稳住系统 (CAR 恢复至监管线), 60 个月零 SFC 违反。

### Phase 2 过程中修复的记账/设计问题

1. **快照恢复后账目分裂**: `state.bank` 与 `state.banks[0]` 被还原成两个对象,
   新旧代码路径各写一个 → SFC 破裂。已修: 单银行时恢复共享实例; 序列化补齐
   `housing_market`; snapshot 版本升至 v2。
2. **多银行聚合代理漂移**: `state.bank` 原为一次性聚合副本, 主循环写入它但校验聚合真银行。
   已改为"主银行语义": `state.bank = banks[0]`, 聚合视图只在 build_balance_sheets 现场求和。
3. **LOLR 资本清零无对手方**: `bank.capital = 0` 无对应记账。换成完整镜像的政府救助:
   gov.debt↑R/gov.other_assets↑R ↔ cb.gov_bonds↑R/cb.bank_reserves↑R ↔ bank.reserves↑R/bank.capital↑R。
4. **同业违约注销漏记**: 债权人扣资本但债权资产未减、债务人负债未注销。
   补三边记账 (claims↓X + reserves↓0.4X|cap↓0.6X; debtor: debt↓X|reserves↓0.4X|cap↑0.6X)。
   银行失败期间同业市场冻结 (停止单边结算)。
5. **违约触发不可达**: 原"负资产+失业>6月"几乎无法同时满足。新增断供计数器
   (连续 miss ≥3 月即触发), 经济含义更贴近现实。
6. **房价初始参数不自洽**: price=200 vs rent 锚定目标 2400 → 必然长期上涨。
   校准为 price=120, rent=0.5, yield=5% (三者自洽); 新增 `housing_initial_ltv`。

### Phase 1 待办（按计划顺序）

> 三项未交付项已并入 **§5.0 前置批次**，作为 Phase 3 Week A 的前置依赖，那里有完整记账规格。

- [ ] P0-a: Stiglitz-Weiss 消费信贷 + LTV/DTI → §5.0
- [ ] P0-b: 债券市场 + 私人持债渠道 → §5.0
- [ ] P0-c: scenarios/*.yaml 场景库 → §5.0

### 已知建模限制（有意简化, 后续修正）

- ~~企业投资不消耗金融资源~~ → **Week A 已关闭**: 存在资本品部门时投资走真实采购
- ~~部门份额不自洽 / 幻影购买~~ → **Week B 已关闭** (demand=labor shares; 限量成交)
- **多部门失业动态两极化**: 温和冲击只削超额需求 (classical 区制, 无失业反应);
  强冲击直接引发破产潮 (u→80%). 缺平滑的中间区制 → Week F 重校准 (CES 启用 +
  库存缓冲目标化). 当前以" rises-and-falls + 零 SFC 违反"为验收口径
- 国债利息默认滚入本金（CB 利润上缴未建模）→ P0-b 部分处理, 剩余项留 Phase 5
- 存款利率为单一聚合利率（无个体层级差异化）→ 多主体化后继续收敛
- **多银行同业敞口初始化挂起**: 临时禁用, 留给 Phase 3 Week E 重新设计主银行语义

---

## 0. 阅读指南

| 章节 | 内容 | 何时读 |
|---|---|---|
| 1. 指导原则 | 编码哲学（仍然生效） | 开始前 |
| 2. 现状结构 | 实际代码目录 + Phase 3 装点 | 熟悉代码时 |
| 3. 测试策略 | 金字塔与原则 | 全程 |
| 4. 历史存档摘要 | Phase 0-2 的取舍与教训 | 回溯设计动机时 |
| 5. **Phase 3-5 实施方案** | **前置批次 + 逐周计划 + 记账规格 + 未决问题** | **当前主文档** |
| 6. 关键依赖 | 实现顺序依据 | 调整顺序时 |
| 7. 附录：早期决策记录 | Q1-Q6 已采纳默认值 | 需要背景时 |

> Phase 0/1 的逐日实施细节与初版计划见 git 历史 (`git log -- IMPLEMENTATION.md`)。

---

## 1. 指导原则

### 1.1 编码哲学

| 原则 | 说明 |
|---|---|
| **SFC 优先** | 任何涉及金钱流动的代码必须经过 SFC 校验。校验是地基，不能事后补。 |
| **可复现优先** | 每个随机数来自 `RNGManager` 命名流。任何"魔术常量"必须配置化。 |
| **接口稳定** | 先定义抽象接口（Protocol/ABC），后写实现。便于替换和测试。 |
| **写测试** | 测试不是事后补——Phase 0 第一个任务就是建测试框架。 |
| **数据契约** | 跨模块数据用 `dataclass` + 类型注解。Polars DataFrame 用于跨主体聚合。 |
| **配置驱动** | 所有参数（CAR 阈值、折旧率、Taylor 系数等）从 YAML/JSON 读，不写死在代码里。 |

### 1.2 优先级

> 如果时间不够，**先做对的不做多的**。

优先级排序：
1. ✅ SFC 校验工作
2. ✅ 月度主循环跑通
3. ✅ 1-2 个核心反馈环（如货币 → 信贷 → 实体）
4. ⚠️ 异质性 / 异质信念（Brock-Hommes）
5. ⚠️ 复杂市场（房产、外汇）
6. ❌ UI / 可视化（Phase 4）
7. ❌ 性能优化（Phase 2+）

### 1.3 反模式（禁止事项）

- ❌ 在 Phase 0 加房产市场
- ❌ 在 Phase 0 用 Brock-Hommes（用静态预期替代）
- ❌ 把"无 SFC 校验"的代码合并到 main
- ❌ 用 `np.random.random()` 等无命名 RNG
- ❌ 在 `step()` 函数里写打印语句（用 logging）
- ❌ 把硬编码参数散落在代码里

---

## 2. 现状结构（实际目录）

```
FinancialSim/
├── DESIGN.md / docs/*.md        # 设计文档
├── IMPLEMENTATION.md            # 本文件
├── pyproject.toml               # 依赖 + ruff/pytest 配置
├── .github/workflows/calibration.yml
├── financial_sim/
│   ├── config.py                # SimConfig (pydantic): Taylor/财政/银行/CAR/异质性/房产/多银行参数
│   ├── core/
│   │   ├── simulation.py        # Simulation: 构建 SFC-balanced 初始态 + run/step
│   │   ├── state.py             # SimulationState + build_balance_sheets() 现场聚合
│   │   └── step.py              # monthly_tick 编排(全部记账镜像所在, ~800 行核心)
│   ├── agents/                  # household / firm / commercial_bank / government / central_bank
│   ├── markets/                 # goods / labor / housing
│   ├── monetary/                # balance_sheets(5类) / sfc(相对容差校验器)
│   ├── expectations/inflation.py# 适应性 + 锚定 + 脱锚
│   ├── network/interbank.py     # 同业敞口(静态; Phase 3 Week E 动态化)
│   ├── simulation/              # rng(RNGManager) / events(ShockEvent) / snapshot(v2 JSON)
│   └── utils/                   # distributions / logging / paths
├── tests/{unit,integration,calibration}/
├── scenarios/                   # (空) Phase 3 前置批次 P0-c 填充
└── reports/
```

Phase 3 新增模块落点见 §5 各周计划。

---

## 3. 测试策略

```
                校准测试  ←─ 蒙特卡洛 (tests/calibration/stylized facts)
                    │
                e2e/集成  ←─ 危机涌现、baseline 稳定性 (tests/integration/)
                    │
                单元测试  ←─ 记账、行为函数、边界值 (tests/unit/, 190+ 个)
```

| 原则 | 说明 |
|---|---|
| **每个 SFC 校验有负向测试** | 故意制造违反，验证能捕获 |
| **每个跨部门资金流双边镜像** | 写新 step 函数前先写分录规格; 配对两侧用同一数值变量 |
| **每个数学公式有数值验证** | 已知输入 → 容差内输出 |
| **每个行为规则有边界测试** | CAR=0、完全失业、零库存不崩溃 |
| **场景×种子回归门禁** | baseline 与 crisis 场景在 CI 全绿，违即停 |

---

## 4. 历史存档摘要（Phase 0-2 取舍与教训）

详细过程见 git log；此处只留影响后续设计的结论：

1. **SFC 记账 bug 都源自同一类错误**: 一侧变动没有对手方（利息资本化漏记收入、LOLR 抹平资本、
   同业违约单边核销、快照别名分裂）。对策已制度化为 §3 原则与 §5 各周的"开工前写死分录规格"。
2. **定价/工资规则必须先校准稳态**: 半年调薪系数 0.5 与房价初始价偏离锚都曾造成爆炸;
   任何行为方程上线前先验证 baseline 60 月价格平稳。
3. **聚合代理对象一律不用**: 只允许"现场求和视图"(build_balance_sheets) 或真实主体本体,
   不维护会漂移的副本。
4. **违约通道必须经济可达**: 触发条件要对应真实压力路径 (断供计数 > 失业时长组合),
   否则机制写了等于没写。

---

## 5. Phase 3-5 实施方案

> 本节为详细实施计划（2026-08-27 制定），替代原概览。写作时基准：
> Phase 0-2 已完成（199 测试全绿，危机涌现验证通过），
> 现有资产：housing/mortgage、多银行(主银行语义)、同业敞口(静态)、事件系统、快照 v2、校准套件雏形。
> 编排原则沿用 §1：SFC 优先——每个模块开工前先写死"双边记账规格"，负向测试随代码提交。

### 4.1 稳态修复尝试（2026-08-27, 未根治, 仅作工具脚手架）

**问题诊断** (120 月 baseline 跑):
- 政策利率被通胀推至 100%+ 或贴 floor (−0.005)
- gov debt 线性发散
- 失业率 (1-2%) ≪ NAIRU (5%) — 失业机制弱
- 校准套件 7 项 stylized facts 中 6 项 "pseudo-passing" (断言被放宽到任意常数 / xfail / skip)

**根因**: 不是单一 bug, 而是三个相互放大的结构性缺陷:
1. **生产函数不响应价格**: `production = productivity × employees` 与价格脱钩 → 库存耗尽时无法扩产 → 价格阶梯 (5%/月) 单调上升
2. **价格规则离散且无上界**: 库存耗尽时按 5% 步长提价, 累计 11 个月到 71% YoY; Taylor rule 又以更高利率反击 → 恶性循环
3. **财政失衡 (G = 0.45 × potential_gdp, T ≈ 0.25 × wage_bill)**: 18% 永久赤字 → CB 货币化 → 银行资本单调增长 → 没有退出阀

**修复尝试与产出**:
- ✅ 工具脚手架: `_bank_dividend_cycle(state)` 在 `step.py` 中定义 (账面转移: `bank.capital ↓D ↔ bank.deposits_from_hh ↑D ↔ h.deposits ↑D`), SFC 平衡已验证, 后续 Phase 3 Week A 调通生产函数后只需 `monthly_tick` 中插入一行调用即可开启
- ✅ 工具脚手架: `config.wealth_effect_coef` 默认 0, 留作 Phase 3 调参用
- ⚠️ `_government_cycle` 中 G 实物化的尝试 (按当前价格扣 `firm.inventory`) 在调用顺序上无法闭环 (G 在 `_household_consumption` 之后跑), 单方面改进会破坏其他机制 (已撤回)
- ❌ 完整稳态无法仅通过调参实现 — 必须重写生产函数 + 价格规则 (Phase 3 Week A 范畴)

**承诺给 Phase 3 Week A 的接入点**:
1. `_bank_dividend_cycle(state)` 已 ready, 一行插入 `monthly_tick` 即可激活
2. `enable_bank_dividends=True` 已为默认, `bank_dividend_car_target=0.10` 已调
3. `_bond_cycle` 默认 OFF 的 bug 已修 (原本即使 config flag 为 False, 函数内默认参数也会让它运行 — 已统一为 False)

### 5.0 前置批次：P1/P2 遗留 + 记账债务清偿（约 2 周，Phase 3 Week A 前必须完成）

原 Phase 1 Week 5-6 有三项未交付，且它们恰好是 Phase 3 的依赖项，按依赖顺序先行：

| 序 | 模块 | 为什么是前置 | 关键文件 |
|---|---|---|---|
| P0-a | **消费信贷市场**（Stiglitz-Weiss 配给 + LTV/DTI） | 资管/投行的对手方是负债家庭；信贷配给逻辑会被企业融资复用 | `markets/credit.py`, `step._consumer_credit_cycle` |
| P0-b | **债券市场**（期限结构 + 私人部门持债渠道） | 关闭"财政赤字 100% CB 承接"的建模限制；投行自营盘需要国债头寸 | `markets/bonds.py`, `step._bond_cycle` (⚠️ 默认关闭, 舍入未解) |
| P0-c | **场景库**（scenarios/*.yaml + loader 测试） | 危机场景目前写死在测试里；Phase 3 每个里程碑都用场景验收 | `scenarios/*.yaml`, `financial_sim/scenarios.py` |

**P0-b 记账规格（预先钉死）**:
- 政府增设 treasury 存款账户（`GovernmentBalanceSheet.treasury_deposits` 字段已存在但从未使用）
- 发债: HH/银行存款 −X ↔ 各自 bonds 持有 ↑X; treasury_deposits ↑X ↔ CB 或银行的对应资产调整
- 国债利息以现金支付（经 treasury），CB 持有部分的利息保留"滚入本金"简化并写入文档
- 新增 SFC 校验第 6/7 项: 债券持有 = 发行；treasury 存款与 CB 负债一致
- 验收: tight_credit / baseline 双场景 24 月零违反

---

### Phase 3：完整经济（计划 6 周）

> 目标: 从"单聚合企业的玩具经济"升级为多部门多主体经济；
> 清偿全部已知建模限制；每个里程碑用一个 YAML 场景验收。

#### Week A: 多部门 + 资本品闭环（消解限制 #1）

| 内容 | 说明 |
|---|---|
| 6 部门 firms 列表化 | consumer/capital/energy/housing_serv/high_tech/services；`state.firms: list[Firm]`，逐部门 `GoodsMarket` 实例 |
| CES 生产函数 | Y = A·(α_K·K^ρ + α_L·L^ρ + α_E·E^ρ + α_M·M^ρ)^(1/ρ)，ρ 由 σ=1/(1−ρ) 标定；先用 stylized 参数表 |
| 中间品投入 M | 供应链矩阵 IO(sector_i→sector_j) 驱动；这是供应链网络的记账前身 |
| **投资实流化** | 企业投资改为向 capital_goods 部门真实采购: 买方 deposits ↓I ↔ 卖方 deposits ↑I（银行两侧镜像）；折旧不变 |

SFC 注记: 这是历史 bug 高发区。规格:任何 I 的分子分母必须同时出现在买卖两家银行账本
（同一家银行则只动 deposits_from_firms 内部一笔）。采购资金不足时走信贷市场（Week C 接入）。
验收: 多部门 baseline 36 月零违反；投资与资本品部门营收恒等。

#### Week B: 劳动市场跨部门流动 + 失业深化

| 内容 | 说明 |
|---|---|
| 失业池机制 | households 按部门搜索工作；搜寻强度 × 保留工资（现状: 单一雇主雇佣所有人） |
| 工资方程完整版 | w_t = w_{t−1}·(预期通胀指数化 + κ·失业缺口)，加长期失业疤痕效应折扣 |
| 部门间再配置 | 收缩部门裁员 → 池 → 扩张部门招聘；招聘命中率 = f(总需求) |

验收: 紧缩场景下失业率能到 8%+ 且回落；Okun 系数量级合理。

#### Week C: 股票市场（Brock-Hommes）+ 交叉持股

| 内容 | 说明 |
|---|---|
| Trader 类 + 7 规则 | beliefs/fitness/softmax 适应；日级子循环独立 RNG 流 `'stocks'` |
| 公司股权发行 | Firm 增加 shares/equity 账户；IPO 把银行贷款置换为股权（资产负债表重组，不动货币总量） |
| 家庭组合选择 | risk_tolerance 驱动 存款↔股票 配置（SFC: 存款在家庭间转移） |
| 交叉持股骨架 | Scale-Free 图上 firms 相互持股；市值核算进 BS 的 stocks 字段（通用 BS 类已支持） |

SFC 注记: 股价波动本身不入账（估值重估）；只有交易清算动存款。**严禁把浮盈变成购买力**
——2008 教训已写入 test_crisis。验收: 波动聚集 autocorr > 0.1（并入校准套件）。

#### Week D: 投资银行 + 资管

| 内容 | 说明 |
|---|---|
| InvestmentBank | 自营股票/国债头寸、VaR 风控、回购融资杠杆、fire-sale 函数完整版 |
| AssetManager | 代理家庭持仓、赎回→被动抛售→净值下跌→更多赎回（赎回螺旋） |
| FSIC 扩展 | BS 类新增两个部门的资本追踪型表（A=L+capital 模式） |

SFC 注记: 回购 = 以证券质押借入现金，记: 资产端 cash↑ / 负债端 repo↑，抵押品做表外登记；
强平双向镜像。验收: 杠杆冲击场景下资管赎回螺旋 + i-bank fire-sale 能把房价/股价冲击
放大 ≥30%（对照无 i-bank 场景）。

#### Week E: 网络动态化

| 内容 | 说明 |
|---|---|
| 同业网络重连 | 静态敞口 → 每季 Core-Periphery 重连（额度受 CAR 约束）；替换现"冻结"补丁 |
| 供应链网络成型 | 分层树 + 少量交叉；断供传导 = 上游减产 → 下游 M 缺口 → CES 产量下调 |
| 外资桩（可选，Q11） | 简单外汇占款账户；不做汇率内生 |

#### Week F: 场景库扩充 + 明斯基验证

2008 / 滞胀 / 战后复苏 / 房产泡沫破裂 四场景 YAML 化（含 trigger_offsets 编排）；
明斯基时刻检验: 内生杠杆积累 → 微小外生冲击触发非线性崩塌（对比不同初始杠杆）。

**Phase 3 验收标准**: ① 全部四场景零 SFC 违反（蒙特卡洛 10 种子×4 场景）;
② 性能: n_households=5000, 12 firms × 6 部门, P95 tick < 2s; ③ stylized facts 从 7 项扩到
10 项全过; ④ 限制清单(#1 投资资源/#2 财政承接)正式关闭并从文档移除。

---

### Phase 4：教学层（计划 6 周）

> 原则: UI 是仿真的只读投影 + 受控干预通道，模型核心不因前端改动。

| 周 | 模块 | 技术要点 |
|---|---|---|
| G1 | FastAPI 服务层 | `POST /sim/create`(seed/config)、`GET /sim/{id}/series`、快照即数据源(snapshot v2 直接复用)；所有状态输出经 Polars DataFrame 聚合 |
| G1 | 干预 DSL | 干预=构造 ShockEvent 进 EventManager（复用现有系统保证可复现/可审计），禁止直接改 agent 状态 |
| G2 | WebSocket tick 流 | 后台线程跑仿真，推送 MacroSnapshot 增量；断线用快照恢复续跑（ReplayManager） |
| G3-4 | Svelte 前端: 4 层下钻 | L1 宏观时序(ECharts) → L2 部门/主体列表 → L3 单主体资产负债表+流量 → L4 网络图(D3: 同业/供应链/持股三视图) |
| G5 | 场景编辑器 | 表单 → SimConfig YAML 校验(pydantic schema 即接口)；预设模板一键加载 |
| G6 | 教程/引导任务 | 3 个交互式课程（通胀、金融危机、货币政策），每课 = 固定 seed + 分步干预脚本 |

工程约束: pydantic SimConfig 直接生成前端表单 JSON Schema；UI 层零科学计算;
Playwright e2e 冒烟测试入 CI。验收: 5 分钟内完成"加息 300bp 观察衰退"教学流程;
100 个并发只读连接不掉帧; 干预操作 100% 进入 shock_log 可回放。

---

### Phase 5：校准与验证（持续运行，与 Phase 4 并行启动）

| 工作流 | 内容 |
|---|---|
| 数据接入 | 美国: SCF 2019+FRED(GDP/失业/联邦基金/Case-Shiller)；中国: CHFS 2019。封装 `analytics/calibration_data.py`，离线缓存到 `reports/data/` |
| 矩匹配 | 目标矩: 均值/波动/自相关/跨期相关(如失业-产出)。方法: 先网格搜索后 Nelder-Mead；参数集限 ≤20 个自由参数 |
| 回归门禁 | CI 里跑 baseline + 2008 两场景，关键矩偏离基线 >25% 则 fail（防重构回归） |
| 教学实验 | 每个教程课程配套"预期现象清单"（如加息→GDP 滞后 2-4 季度下降），实测对照写入 reports/ |
| 版本化报告 | 每次 release 生成 `reports/calibration_<date>.md`: 参数表、矩对照表、失败项与调参建议 |

风险与顺序: 校准易陷入"调一个坏三个"，规矩是**一次只动一组参数，先定结构性参数
（份额/弹性），再定行为参数（MPC 分布/风险偏好），政策规则最后**。

---

### 未决问题（需用户决策后启动对应模块）

| # | 问题 | 建议 |
|---|---|---|
| Q7 | 债券市场是否引入期限分层（3 个月/3 年/10 年）还是单一永久债？ | 单一债起步，利率用期限结构公式定价（Nelson-Siegel 一因子） |
| Q8 | 多部门firm数: 每 sector 12 家够不够统计意义？ | 12 家起步; 异质性靠 within-sector 分布而非家数 |
| Q9 | Brock-Hommes 日级循环会显著拖慢性能，是否降频到周级？ | 先日级跑通测性能，>预算再降频 |
| Q10 | 外资桩要不要进 MVP？ | 不进; 放 Phase 3 可选实验特性 |
| Q11 | Phase 4 技术栈确认: Svelte + FastAPI 是否 OK？ | 是; 若团队更熟 React 改 React 也行, WebSocket 协议不变 |
| Q12 | Phase 5 用美国数据还是中国数据为主？ | 双轨，先美国(FRED 免费/API 友好)，CHFS 需申请数据 |

---

## 6. 关键依赖（实现顺序依据）

| 上游 | 下游 | 说明 |
|---|---|---|
| SFC 校验 | 任何流量代码 | SFC 必须先于其他工作 |
| RNGManager | 任何初始化 | 异质性种子不能凭空 |
| 5 BS 类 | 主体类 | 主体必须先有 BS |
| tick 编排 | 主体决策 | tick 决定调用顺序 |
| 主体决策 | 市场出清 | 主体先决策，市场再出清 |
| 主体决策 | 宏观聚合 | 聚合基于主体状态 |

---

---

## 7. 附录：早期决策记录（原 §8 未决问题 Q1-Q6）

实现期间均按建议默认值执行，记录如下避免重复讨论：

| # | 问题 | 采纳结果 |
|---|---|---|
| Q1 | 异质家庭分布初始参数 | 截断正态(储蓄率/MPC) + LogNormal(工资 σ=0.3, 存款中位数 20)，SCF 校准推迟到 Phase 5 |
| Q2 | CES 部门参数 | stylized values（真实数据 Phase 5 接入） |
| Q3 | 惯性 Taylor Rule | 采用, smoothing=0.85, 下限 −0.5% |
| Q4 | MVP 家庭数量 | Phase 0/2 用 100-1000; Phase 3 目标 5000 |
| Q5 | Brock-Hommes 规则数 | 全部 7 个，配置可开关（Phase 3 Week C 实现） |
| Q6 | 外资模块 | MVP 不加，转 §5 未决问题 Q10 |

新的待决问题 Q7-Q12 见 §5 末尾。

---

## 8. 已识别风险（对照后续阶段）

| 风险 | 阶段 | 缓解 |
|---|---|---|
| 多主体化后 tick 性能超标 | Phase 3 | Polars 向量化 + Week F 统一压测; 不达标降 BH 循环频率(Q9) |
| 校准调参"动一发坏全身" | Phase 5 | 一次一组参数; CI 矩回归门禁 |
| UI 层耦合模型内核 | Phase 4 | 干预只走 ShockEvent DSL; 状态只从快照投影 |
