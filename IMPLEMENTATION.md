# ABM 宏观经济仿真器：实现计划

> 状态：Phase 0 ✅ / Phase 1 ✅（核心链路）/ Phase 2 ✅（金融层扩展 + 危机涌现）
> 最后更新：2026-08-27
> 对应设计：[DESIGN.md](DESIGN.md) + [docs/](docs/)

---

## 进度看板（2026-08-27 更新）

**测试基线**: 199 passed · ruff clean · baseline 与危机场景均零 SFC 违反

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

- [ ] Week 5: Stiglitz-Weiss 信贷配给 + LTV/DTI（家庭消费信贷, 区别于房贷）
- [ ] Week 6: Brock-Hommes 股票市场 + 债券期限结构
- [x] ~~ShockEvent 事件系统~~ ✅ (Phase 1 late: events.py + 9 个预设)
- [x] ~~失业机制 / 劳动摩擦~~ ✅ (Phase 1 late commit)
- [x] ~~stylized facts 校准套件~~ ✅ (Phase 1 late: tests/calibration)
- [ ] Week 8: scenarios/*.yaml 场景库 (含 2008 crisis 场景配置化)

### 已知建模限制（有意简化, 三期修正）

- 企业投资不消耗金融资源（隐含留存利润实物化假设）
- 财政赤字 100% 由 CB 承接（无私人部门持债渠道）
- 国债利息默认滚入本金（CB 利润上缴未建模）
- 存款利率为单一聚合利率（无个体层级差异化）

---

## 0. 阅读指南

本文档把设计文档转化为可执行的实施路线。每个 Phase 都有：
- 明确的目标
- 要创建的目录/文件
- 步骤顺序（依赖关系）
- 验收标准

---

| 章节 | 内容 | 何时读 |
|---|---|---|
| 1. 指导原则 | 编码哲学 | 开始前 |
| 2. 包结构 | 文件组织 | 开始前 |
| 3. Phase 0 细节 | **Week 1-2 做什么** | **立即读** |
| 4. Phase 1 细节 | Week 3-8 做什么 | Phase 0 完成后 |
| 5. Phase 2-5 概览 | 后续阶段方向 | 中期参考 |
| 6. 依赖图 | 实现顺序的依据 | 调整顺序时 |
| 7. 测试策略 | 验证方法 | 全程 |
| 8. 风险与未决 | 待解问题 | 决策时 |

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

## 2. 包结构

### 2.1 顶层目录

```
FinancialSim/
├── DESIGN.md              # 顶层设计概述
├── IMPLEMENTATION.md      # 本文件
├── README.md              # 项目入口
├── pyproject.toml         # 包管理 + 依赖
├── requirements.txt       # 生产依赖（pin 版本）
├── requirements-dev.txt   # 开发依赖
├── .gitignore
├── .github/
│   └── workflows/
│       └── calibration.yml   # CI 跑校准测试
├── docs/                  # 设计文档（已存在）
│   ├── AGENTS.md
│   ├── MARKETS.md
│   ├── MONETARY.md
│   ├── EXPECTATIONS.md
│   ├── SIMULATION.md
│   └── VALIDATION.md
├── financial_sim/         # ← 主代码包
│   ├── __init__.py
│   ├── config.py          # 配置加载
│   ├── core/              # 仿真核心
│   ├── agents/            # 主体类
│   ├── markets/           # 市场模块
│   ├── monetary/          # 货币 + SFC
│   ├── expectations/      # 预期机制
│   ├── network/           # 网络结构
│   ├── simulation/        # 调度、事件、可复现
│   ├── analytics/         # 宏观聚合 + 报告
│   └── utils/             # 工具（RNG、性能监控、日志）
├── tests/
│   ├── unit/              # 单元测试
│   ├── calibration/       # 校准测试
│   └── integration/       # 集成测试
├── scenarios/             # 预设场景配置（YAML）
│   ├── baseline.yaml
│   ├── loose_credit.yaml
│   └── ...
└── reports/               # 校准报告输出
```

### 2.2 详细结构（Phase 1 结束时）

```
financial_sim/
├── __init__.py
├── config.py                       # 配置 schema + loader
├── core/
│   ├── __init__.py
│   ├── simulation.py              # Simulation 主类
│   ├── state.py                   # SimulationState
│   └── step.py                    # 月度 tick 编排
├── agents/
│   ├── __init__.py
│   ├── base.py                    # Agent 基类 + Protocol
│   ├── household.py               # Household + HouseholdBalanceSheet
│   ├── firm.py                    # Firm + FirmBalanceSheet
│   ├── commercial_bank.py         # CommercialBank + BalanceSheet
│   ├── government.py              # Government + BalanceSheet
│   ├── central_bank.py            # CentralBank + BalanceSheet
│   └── default.py                 # 违约与处置
├── markets/
│   ├── __init__.py
│   ├── goods.py                   # 商品市场
│   ├── labor.py                   # 劳动市场
│   ├── credit.py                  # 信贷市场
│   ├── stocks.py                  # 股票市场（Phase 1：静态预期）
│   ├── housing.py                 # 房产市场（Phase 2）
│   └── bonds.py                   # 债券市场
├── monetary/
│   ├── __init__.py
│   ├── sfc.py                     # SFC 校验
│   ├── balance_sheets.py          # 5 个资产负债表类
│   ├── flow_matrix.py             # 流量矩阵定义
│   ├── policy.py                  # Taylor Rule 等
│   └── transmission.py            # 利率传导链
├── expectations/
│   ├── __init__.py
│   ├── base.py                    # 预期基类
│   ├── static.py                  # Phase 1 用：固定预期
│   ├── brock_hommes.py            # Phase 2：Brock-Hommes
│   └── inflation.py               # 通胀预期（4.6）
├── network/
│   ├── __init__.py
│   ├── credit.py                  # 自适应信贷网络
│   └── (Phase 2: interbank, supply_chain)
├── simulation/
│   ├── __init__.py
│   ├── scheduler.py               # 多尺度调度
│   ├── events.py                  # 事件系统
│   ├── rng.py                     # RNGManager
│   ├── snapshot.py                # StateSnapshot
│   ├── replay.py                  # ReplayManager
│   └── perf.py                    # PerfMonitor
├── analytics/
│   ├── __init__.py
│   ├── aggregates.py              # 宏观聚合
│   └── reports.py                 # 报告生成
└── utils/
    ├── __init__.py
    ├── distributions.py           # 异质性分布工具
    ├── logging.py
    └── paths.py
```

### 2.3 测试结构

```
tests/
├── conftest.py                    # pytest 共享 fixtures
├── unit/
│   ├── test_sfc.py                # SFC 校验
│   ├── test_balance_sheets.py     # 5 个 BS 类
│   ├── test_routing.py            # 流量路由
│   ├── test_household.py          # 家庭行为
│   ├── test_firm.py               # 企业行为
│   ├── test_bank.py               # 银行行为
│   ├── test_default.py            # 违约处置
│   ├── test_wage.py               # 工资方程
│   ├── test_inflation.py          # 通胀预期
│   ├── test_credit.py             # 信贷配给
│   ├── test_scheduler.py          # tick 顺序
│   ├── test_rng.py                # RNG 流管理
│   ├── test_snapshot.py           # 快照
│   └── test_replay.py             # 重放
├── calibration/
│   ├── conftest.py                # 蒙特卡洛 fixture
│   ├── test_stylized_facts.py     # 7 个 stylized facts
│   └── test_performance.py        # 性能预算
└── integration/
    └── test_e2e.py                # 端到端：跑 N 个月，校验所有指标
```

---

## 3. Phase 0：原型（Week 1-2）

> **目标**：用最小代码验证"会计内核 + 月度循环 + 主体决策"这三点能跑通。
> 这是整个项目的"骨架"——后面所有工作都挂在这个骨架上。

### 3.1 Phase 0 范围（必须做）

| # | 模块 | 复杂度 | 关键文件 |
|---|---|---|---|
| 1 | 项目脚手架 | 低 | `pyproject.toml`, `conftest.py`, `utils/logging.py` |
| 2 | SFC 5 个 BS 类 | 中 | `monetary/balance_sheets.py` |
| 3 | 流量矩阵 + SFC 校验 | 中 | `monetary/flow_matrix.py`, `monetary/sfc.py` |
| 4 | 简化 Household | 中 | `agents/household.py` |
| 5 | 简化 Firm（1 部门）| 中 | `agents/firm.py` |
| 6 | 简化 CommercialBank（1 家）| 中 | `agents/commercial_bank.py` |
| 7 | Government + CentralBank | 低 | `agents/government.py`, `agents/central_bank.py` |
| 8 | 月度 tick 编排 | 中 | `core/simulation.py`, `core/step.py` |
| 9 | 基本市场：商品 + 劳动 | 中 | `markets/goods.py`, `markets/labor.py` |
| 10 | RNG 管理 | 低 | `simulation/rng.py` |
| 11 | 单元测试：SFC + 主体 | 中 | `tests/unit/` |
| 12 | **最简 e2e：跑 12 个月** | 低 | `tests/integration/test_e2e.py` |

### 3.2 Phase 0 显式不做

| 不做 | 推迟到 |
|---|---|
| 房产市场 | Phase 2 |
| 投资银行 / 资管 | Phase 2 |
| Brock-Hommes | Phase 2 |
| 事件系统（外生冲击） | Phase 2 |
| 性能监控埋点 | Phase 1 末 |
| 快照 / 重放 | Phase 1 中 |
| 网络结构 | Phase 1 末 / Phase 2 |
| UI / 可视化 | Phase 4 |

### 3.3 Phase 0 详细步骤

#### Day 1-2：项目脚手架 + 工具

```bash
# 1. 创建项目骨架（目录已在文档中定义）
# 2. pyproject.toml
# 3. requirements.txt
# 4. .gitignore
# 5. CI workflow（先空跑）

# 关键文件：
# - pyproject.toml (Python 3.11, setuptools)
# - requirements.txt: polars, numpy, numba, scipy, networkx, pyarrow, duckdb, pydantic
# - requirements-dev.txt: pytest, pytest-cov, ruff, mypy
# - utils/logging.py: 结构化日志
# - conftest.py: 共享 fixtures
```

**验收**：能 `pip install -e '.[dev]'` 成功，能 `pytest --collect-only`。

#### Day 3-4：SFC 内核（最重要）

**这是地基。先做，且必须做对。**

```
monetary/balance_sheets.py
  ├── HouseholdBalanceSheet (dataclass + sum_assets/liabilities/net_worth)
  ├── FirmBalanceSheet
  ├── CommercialBankBalanceSheet
  ├── GovernmentBalanceSheet
  ├── CentralBankBalanceSheet
  └── 单元测试：每个 BS 类的恒等式

monetary/flow_matrix.py
  └── TRANSACTION_MATRIX: 字典,键 (source, target, name)

monetary/sfc.py
  ├── validate_sfc(state) -> list[str]
  ├── 6 项校验：BS、净借贷、货币守恒、CB BS、债务恒等、NW 变动
  └── 单元测试：构造已知违反，校验能否捕获
```

**验收**：
- `pytest tests/unit/test_balance_sheets.py -v` 全过
- `pytest tests/unit/test_sfc.py -v` 全过
- 故意制造 1 个 SFC 违反（人为改数字），确认 `validate_sfc` 返回错误

#### Day 5-7：简化主体类

**Phase 0 的主体是"能跑起来的最简版"。**

```python
# agents/household.py — Phase 0 简化版
@dataclass
class Household:
    id: str
    wealth: float = 0.0
    income: float = 0.0
    consumption: float = 0.0
    wage: float = 0.0
    employed: bool = True
    sector: str = 'consumer_goods'
    
    # Phase 1 再加: education, savings_rate, MPC, debt, assets...
    
    def decide_consumption(self, state) -> float:
        # Phase 0 简化: c = 0.7 * income
        return 0.7 * self.income
```

**字段保持精简——每个字段都要在 Phase 0 真正被用到。**

同样的简化思路应用到 Firm（生产函数用最简单的 Cobb-Douglas）、Bank（只支持存款 + 贷款）。

**验收**：每个主体的 `__init__` 和 1-2 个核心决策函数有单元测试。

#### Day 8-10：核心循环

```
core/state.py
  └── SimulationState: 持有所有主体的 DataFrame + 资产负债表 + 宏观变量

core/simulation.py
  └── Simulation:
      def __init__(self, config, seed)
      def step(self)           # 调 step.monthly_tick
      def run(self, n_ticks)

core/step.py
  └── monthly_tick(t, state):
      # 按 docs/SIMULATION.md 8.2 的 5 个阶段
      # Phase 0 简化: 跳过阶段 1（日级循环）、阶段 4（违约）
```

**关键**：每一步执行后调用 `validate_sfc`。任何错误立即抛出。

#### Day 11-12：最小市场 + 简单决策

```
markets/goods.py
  └── step(state): 汇总需求与供给, 调整价格 (库存缓冲)

markets/labor.py
  └── step(state): 失业率计算 + 简单雇佣
```

**注意**：Phase 0 的商品市场**不要做卡尔沃定价**——用最简单的价格调整。工资用最简的指数化。

#### Day 13-14：e2e 验证 + 修 bug

```python
# tests/integration/test_e2e.py

def test_run_12_months_no_sfc_violation():
    """跑 12 个月，不应有任何 SFC 违反"""
    sim = Simulation(config='baseline', seed=42, n_households=1000, n_firms=50)
    sim.run(n_ticks=12)
    assert len(sim.sfc_violations) == 0
    assert sim.state.t == 12

def test_macro_variables_in_reasonable_range():
    """宏观变量应在合理范围"""
    sim = Simulation(config='baseline', seed=42)
    sim.run(n_ticks=24)
    # GDP 不应为负, 不应爆炸
    assert 0.5 < sim.state.real_gdp < 5.0  # 相对初始
    # 通胀在 -5% 到 +20% 之间
    assert -0.05 < sim.state.inflation_yoy < 0.20
```

### 3.4 Phase 0 验收标准（必须全过）

| # | 标准 | 验证 |
|---|---|---|
| 1 | `pip install -e '.[dev]'` 成功 | 命令 |
| 2 | `pytest tests/unit/` 全过（>30 个测试）| 命令 |
| 3 | `pytest tests/integration/test_e2e.py` 通过 | 命令 |
| 4 | 跑 12 个月零 SFC 违反 | e2e |
| 5 | 跑 24 个月宏观变量在合理范围 | e2e |
| 6 | 代码行数 < 1500 行（Phase 0 应精简）| `cloc` |
| 7 | 所有公共函数有 docstring | ruff check |
| 8 | 无 `print()`，全部用 `logger` | ruff check |
| 9 | 无硬编码参数（除默认值）| ruff check |

---

## 4. Phase 1：最小可工作核心（Week 3-8）

> **目标**：把 DESIGN.md Phase 1 表格中的 12 项全部实现。验证"经济仿真"这个抽象成立。

### 4.1 Phase 1 范围

| # | 模块 | 关键内容 |
|---|---|---|
| 1 | 完整 Household（个体级）| 永久收入消费、财富效应、异质性 |
| 2 | 完整 Firm（3 部门）| CES 生产、卡尔沃定价、托宾 Q 投资、资本折旧 |
| 3 | 完整 CommercialBank | 利率定价、利润循环、CAR/LCR、贷款评估 |
| 4 | Government 完整预算 | 税收、转移支付、国债发行 |
| 5 | CentralBank Taylor Rule | 完整传导链、政策反应 |
| 6 | 完整劳动市场 | 工资议价方程（修正版）、失业摩擦 |
| 7 | 完整信贷市场 | Stiglitz-Weiss 配给、LTV/DTI 约束 |
| 8 | 股票市场（Brock-Hommes）| 7 规则、日级 tick、信念适应 |
| 9 | 债券市场 | 期限结构 |
| 10 | 通胀预期（异质）| 适应性 + 锚定 + 脱锚机制 |
| 11 | 事件系统 | ShockEvent + 预设库 |
| 12 | 快照 + 重放 | Parquet + ReplayManager |
| 13 | 性能监控埋点 | PerfMonitor |
| 14 | 校准测试 | 7 个 stylized facts |

### 4.2 实施顺序（关键路径）

```
Week 3：
  ├── 1. 完整 Household（永久收入消费 + 财富效应）
  ├── 2. 完整 Firm（Cobb-Douglas 起步 → CES）
  └── 3. 完善 tick 编排（加入通胀预期、央行决策）

Week 4：
  ├── 4. 完整 CommercialBank（利率定价 + 利润循环）
  ├── 5. 完整 Government 预算
  └── 6. 完整 CentralBank + 利率传导

Week 5：
  ├── 7. 完整劳动市场（工资方程 + 摩擦）
  ├── 8. 完整信贷市场（Stiglitz-Weiss + 异质 LTV/DTI）
  └── 9. 通胀预期异质（家庭 vs 企业 vs 央行）

Week 6：
  ├── 10. 股票市场（Brock-Hommes 7 规则）
  ├── 11. 债券市场（期限结构）
  └── 12. 事件系统（ShockEvent）

Week 7：
  ├── 13. 快照 + 重放
  ├── 14. 性能监控埋点
  └── 15. 异质家庭分布（5 个分布）

Week 8：
  ├── 16. 校准测试套件（7 个 stylized facts）
  ├── 17. 修 bug + 性能调优
  └── 18. 文档 + 教程
```

### 4.3 Phase 1 详细任务

#### Week 3：完善主体行为

**Household 完整版**：
```python
@dataclass
class Household:
    # Phase 0 字段 +
    education: float           # 0-1
    savings_rate: float        # 异质
    mpc: float                 # 异质
    risk_tolerance: float      # 异质
    debt: float
    deposits: float
    stocks: float
    
    def decide_consumption(self, state) -> float:
        """永久收入 + 财富效应 + 流动性约束"""
        # 见 AGENTS.md 3.2.2 的完整版
        pass
    
    def decide_portfolio(self, state):
        """风险偏好驱动资产配置"""
        pass
```

**Firm 完整版**（CES 生产函数）：
```python
def produce(firm, K, L, E, M, state):
    """Y = A * (α_K * K^ρ + α_L * L^ρ + α_E * E^ρ + α_M * M^ρ)^(1/ρ)"""
    pass

def depreciation(firm):
    """K(t+1) = K(t) * (1 - δ)"""
    pass

def pricing_decision(firm, state):
    """卡尔沃定价：(1-θ) 概率调价"""
    pass
```

#### Week 4：金融部门

**CommercialBank 完整版**：
- 利率定价（base + 风险溢价 + 顺周期调整）
- 利润循环（收入 - 成本 - NPL 拨备）
- CAR/LCR/NSFR 计算
- 贷款评估（lending_score）

**Government**：
- 完整预算约束（ΔB = G + TR + INT - T）
- 税收计算
- 自动稳定器（失业救济）

**CentralBank**：
- Taylor Rule（含平滑）
- OMO 操作
- 利率传导（政策利率 → 同业 → 存贷）

#### Week 5：劳动 + 信贷 + 通胀预期

**劳动市场**：
- 完整工资议价方程（修正版，去掉双重计价）
- 失业摩擦（job_search_intensity × 保留工资）
- 疤痕效应

**信贷市场**：
- Stiglitz-Weiss 配给
- LTV/DTI 约束
- 银行评估函数

**通胀预期**：
- 家庭适应性预期
- 企业投入品驱动
- 央行模型预测
- 脱锚机制

#### Week 6：资产市场 + 事件

**股票市场**：
- 7 个 Brock-Hommes 规则
- Trader 类（beliefs, fitness）
- 适应学习（softmax + 衰减）
- 做市商价格形成
- 日级 tick

**债券市场**：
- 期限结构（Nelson-Siegel 简化）
- 期望短期利率

**事件系统**：
- ShockEvent 数据类
- PRESET_SHOCKS 库
- apply_shocks() 注入点

#### Week 7：基础设施

**快照 + 重放**：
```python
class StateSnapshot:
    def save(state, path) -> None
    @classmethod
    def load(path) -> SimulationState

class ReplayManager:
    def replay(path, end_tick) -> SimulationState
    def fork(path, change_fn) -> SimulationState
```

**性能监控**：
```python
perf = PerfMonitor()
with perf.measure('monthly_tick'):
    ...
print(perf.summary())
```

**异质性分布**：
- 5 个分布在 `utils/distributions.py`
- 在初始化时使用 `RNGManager.stream('household_init')`

#### Week 8：校准 + 收尾

**校准测试**：
- 7 个 stylized facts 测试
- 性能预算测试
- 端到端集成测试

**调优**：
- 根据测试结果调整参数
- 修复 SFC 违反
- 修复性能瓶颈

### 4.4 Phase 1 验收标准

| # | 标准 | 验证 |
|---|---|---|
| 1 | 所有 Phase 0 标准仍然通过 | 回归 |
| 2 | 7 个 stylized facts 测试全过 | pytest |
| 3 | 性能预算达标（P95 < 500ms）| test_performance |
| 4 | 蒙特卡洛 50 次跑全部零 SFC 违反 | calibration |
| 5 | 至少 1 个预设场景能跑通（baseline）| e2e |
| 6 | 能从快照恢复 + 重放 + 分叉 | unit |
| 7 | 帕累托尾能涌现（top 1% > 30%）| calibration |
| 8 | 股价波动聚集（autocorr > 0.1）| calibration |
| 9 | 文档更新（README + tutorial）| review |

---

## 5. Phase 2-5 概览

### Phase 2：金融层扩展（Week 9-14）

| 模块 | 复杂度 | 关键内容 |
|---|---|---|
| 多家商业银行 | 高 | Core-Periphery 网络 |
| 投资银行 | 高 | 自营交易、VaR、回购融资 |
| 资管/保险 | 中 | 赎回螺旋、代理人业务 |
| 房产市场 | 中 | 租金锚定、月度调整 |
| Fire-sale externality | 高 | 完整数学函数 |
| 银行失败处置 | 中 | 完整处置流程 |
| 通胀危机测试 | 中 | 验证明斯基涌现 |

**关键验证**：跑出 2008 风格的危机。

### Phase 3：完整经济（Week 15-20）

| 模块 | 关键内容 |
|---|---|
| 6 部门 + 完整 CES | 能源、住房、高科技 |
| 完整 8 类主体 | 投资银行、资管、外资桩 |
| 自适应信贷网络 | 关系贷款 + 粗筛 |
| 供应链网络 | 分层树 + 交叉 |
| 资产交叉持股 | Scale-Free |
| 场景库（2008、滞胀、战后复苏）| YAML 配置 |

### Phase 4：教学层（Week 21-26）

| 模块 | 技术栈 |
|---|---|
| 4 层下钻 UI | Svelte |
| 时间序列图 | ECharts |
| 网络图 | D3.js |
| 场景编辑器 | Svelte 表单 |
| 实时干预界面 | WebSocket |
| 教程 / 引导任务 | 静态 + 交互 |

### Phase 5：校准与验证（持续）

- 真实历史数据对比
- 校准参数微调
- 教学实验设计
- 用户反馈迭代

---

## 6. 依赖图（实现顺序依据）

```
                          ┌─────────────┐
                          │   pyproject │ ← Day 1
                          └──────┬──────┘
                                 │
                          ┌──────▼──────┐
                          │   logging   │ ← Day 1
                          └──────┬──────┘
                                 │
                  ┌──────────────┼──────────────┐
                  │              │              │
           ┌──────▼─────┐ ┌─────▼─────┐ ┌──────▼─────┐
           │ RNGManager │ │  Config   │ │  Paths    │
           └──────┬─────┘ └─────┬─────┘ └──────┬─────┘
                  │             │              │
                  └─────────────┼──────────────┘
                                │
                  ┌─────────────▼──────────────┐
                  │   5 BS classes + SFC 校验 │ ← Day 3-4 (CRITICAL PATH)
                  └─────────────┬──────────────┘
                                │
                  ┌─────────────▼──────────────┐
                  │   流量矩阵 + 路由          │ ← Day 5
                  └─────────────┬──────────────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                 │
       ┌──────▼─────┐    ┌──────▼─────┐    ┌──────▼─────┐
       │ Household  │    │   Firm     │    │   Bank     │ ← Day 5-7
       └──────┬─────┘    └──────┬─────┘    └──────┬─────┘
              │                 │                 │
              └─────────────────┼─────────────────┘
                                │
                  ┌─────────────▼──────────────┐
                  │   Government + CB         │ ← Day 7
                  └─────────────┬──────────────┘
                                │
                  ┌─────────────▼──────────────┐
                  │   月度 tick 编排            │ ← Day 8-10
                  └─────────────┬──────────────┘
                                │
                  ┌─────────────▼──────────────┐
                  │   基本市场 + 决策           │ ← Day 11-12
                  └─────────────┬──────────────┘
                                │
                  ┌─────────────▼──────────────┐
                  │   e2e 测试 + 修 bug         │ ← Day 13-14
                  └─────────────┬──────────────┘
                                │
                          ✅ Phase 0
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
  ┌─────▼─────┐          ┌──────▼──────┐         ┌──────▼──────┐
  │ 完整主体  │          │ 完整金融市场 │         │ 预期机制    │
  │ (Week 3) │          │ (Week 4-5)  │         │ (Week 5-6)  │
  └─────┬─────┘          └──────┬──────┘         └──────┬──────┘
        │                       │                       │
        └───────────────────────┼───────────────────────┘
                                │
                  ┌─────────────▼──────────────┐
                  │   资产市场 + 事件           │ ← Week 6
                  └─────────────┬──────────────┘
                                │
                  ┌─────────────▼──────────────┐
                  │   快照 + 重放 + 监控        │ ← Week 7
                  └─────────────┬──────────────┘
                                │
                  ┌─────────────▼──────────────┐
                  │   校准测试 + 调优           │ ← Week 8
                  └─────────────┬──────────────┘
                                │
                          ✅ Phase 1
```

### 关键依赖

| 上游 | 下游 | 说明 |
|---|---|---|
| SFC 校验 | 任何流量代码 | SFC 必须先于其他工作 |
| RNGManager | 任何初始化 | 异质性种子不能凭空 |
| 5 BS 类 | 主体类 | 主体必须先有 BS |
| tick 编排 | 主体决策 | tick 决定调用顺序 |
| 主体决策 | 市场出清 | 主体先决策，市场再出清 |
| 主体决策 | 宏观聚合 | 聚合基于主体状态 |

---

## 7. 测试策略

### 7.1 测试金字塔

```
                ┌────────────────────┐
                │  e2e / 集成测试     │  ← 跑完整仿真，验证涌现
                │   (5-10 个)         │
                └──────────┬─────────┘
                           │
                ┌──────────▼─────────┐
                │  校准测试           │  ← 蒙特卡洛 50 次
                │  (7-10 个)          │
                └──────────┬─────────┘
                           │
                ┌──────────▼─────────┐
                │  单元测试           │  ← 每个函数、每个类
                │  (100+ 个)          │
                └────────────────────┘
```

### 7.2 测试原则

| 原则 | 说明 |
|---|---|
| **每个 SFC 校验都有负向测试** | 故意制造违反，验证能捕获 |
| **每个数学公式都有数值验证** | 输入已知参数，验证输出在容差内 |
| **每个行为规则都有边界测试** | 极端参数（CAR=0, 完全失业）不崩溃 |
| **蒙特卡洛 50 次** | 跑 5 个场景 × 10 个种子，验证涌现 |
| **性能预算必测** | 每次提交检查性能不回归 |

### 7.3 关键测试清单（Phase 1）

```
tests/unit/
  test_balance_sheets.py     ─ 5 个 BS 类
  test_sfc.py                ─ 6 项校验 + 已知违反
  test_routing.py            ─ 流量路由正确性
  test_household.py          ─ 消费决策、异质性分布
  test_firm.py               ─ CES 生产、定价、折旧
  test_bank.py               ─ 利率定价、利润循环、CAR
  test_government.py         ─ 预算约束、税收、国债
  test_central_bank.py       ─ Taylor Rule、OMO
  test_default.py            ─ 违约判定、损失分配
  test_wage.py               ─ 工资议价方程
  test_inflation.py          ─ 通胀预期、脱锚
  test_credit.py             ─ 信贷配给、LTV/DTI
  test_stocks.py             ─ Brock-Hommes 7 规则
  test_bonds.py              ─ 期限结构
  test_events.py             ─ ShockEvent
  test_scheduler.py          ─ tick 顺序
  test_rng.py                ─ RNG 流独立性
  test_snapshot.py           ─ 快照与恢复
  test_replay.py             ─ 重放与分叉
  test_perf.py               ─ 性能监控

tests/calibration/
  test_stylized_facts.py     ─ 7 个 stylized facts
  test_scenarios.py          ─ 5 个场景

tests/integration/
  test_e2e_baseline.py       ─ 12 个月 baseline
  test_e2e_tight_credit.py   ─ 12 个月紧信贷
  test_e2e_loose_credit.py   ─ 12 个月宽信贷
```

---

## 8. 风险与未决问题

### 8.1 已识别风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| SFC 校验调试耗时 | 阻塞 Phase 0 | Day 3-4 集中做 SFC，提前发现 |
| 主体决策写得太复杂 | 难调试 | Phase 0 用最简化版本，Phase 1 再加异质 |
| 性能不达标 | Phase 1 末出问题 | Week 7 加性能监控埋点，提前发现 |
| 校准测试频繁失败 | Phase 1 末拖延 | Week 8 留缓冲期，准备第 9 周 |
| 数据结构选错 | 后期重构 | Phase 0 用 Polars，向量化友好 |

### 8.2 未决问题（需要用户决策）

#### Q1：异质家庭分布的初始参数

DESIGN 给了分布族（LogNormal 等），但**具体参数**未定：
- LogNormal 财富分布：μ 和 σ 选多少？
- 初始财富中位数？
- 初始储蓄率中位数？

**建议**：先用 US Survey of Consumer Finances (SCF) 2019 数据校准。如果用中国数据则用 CHFS 2019。

#### Q2：部门参数

CES 生产函数的 σ、α_K、α_L 等参数表设计有，但**校准值**未定：
- 直接用 KLEM 数据库？
- 用中国/美国的产业数据？
- 还是用 stylized values？

**建议**：先用 stylized values（设计文档表中的值），Phase 5 校准时再用真实数据。

#### Q3：Taylor Rule 参数

设计文档给了 π_π = 1.5、π_y = 0.5，但**是否使用"惯性 Taylor"**（含利率平滑）？

**建议**：用，含平滑（标准做法，避免过度反应）。

#### Q4：MVP 家庭数量

设计文档说 MVP 用 1K-5K Phase 1 起步。但 SFC 校验开销大：
- 1K 家庭：每 tick 计算轻，但统计意义弱
- 10K 家庭：帕累托尾更明显，但 CPU 重

**建议**：Phase 0 用 1K（验证 SFC）；Phase 1 切到 5K；Phase 2+ 考虑 10K+。

#### Q5：Brock-Hommes 的 7 个规则

**全部 7 个都要实现，还是精简到 4-5 个**？

**建议**：完整实现 7 个，但允许在配置中开关个别规则。后期根据实证结果调。

#### Q6：外资模块何时加

**Phase 3 是否加外汇市场**？

**建议**：MVP 不加。Phase 3 看用户需求决定。


## 9. 附录：关键文件模板

### 9.1 `pyproject.toml` 模板

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "financial_sim"
version = "0.0.1"
description = "Agent-based macroeconomic simulation for education"
requires-python = ">=3.11"
dependencies = [
    "polars>=0.20",
    "numpy>=1.25",
    "numba>=0.58",
    "scipy>=1.11",
    "networkx>=3.2",
    "pyarrow>=14",
    "duckdb>=0.9",
    "pydantic>=2.5",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4",
    "pytest-cov>=4.1",
    "pytest-xdist>=3.5",
    "ruff>=0.1",
    "mypy>=1.7",
]

[tool.setuptools.packages.find]
where = ["."]
include = ["financial_sim*"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "C4", "RET", "SIM"]
ignore = ["E501"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --tb=short --strict-markers"
markers = [
    "calibration: calibration tests (slow)",
    "integration: integration tests",
]
```

### 9.2 第一个 SFC 测试示例

```python
# tests/unit/test_sfc.py
from financial_sim.monetary.balance_sheets import (
    HouseholdBalanceSheet, FirmBalanceSheet,
    CommercialBankBalanceSheet, GovernmentBalanceSheet,
    CentralBankBalanceSheet,
)
from financial_sim.monetary.sfc import validate_sfc

def test_household_balance_sheet_identity():
    """A = L + NW 必须成立"""
    bs = HouseholdBalanceSheet(
        cash=1000, deposits=5000, stocks=2000, bonds=1000,
        housing_self=30000, housing_investment=0, consumer_durables=5000,
        mortgage=20000, consumer_loan=3000, other_debt=1000,
    )
    assert abs(bs.sum_assets() - bs.sum_liabilities() - bs.net_worth) < 1e-6

def test_sfc_catches_known_violation():
    """人为违反 BS 恒等式，验证 SFC 能捕获"""
    bs = HouseholdBalanceSheet(
        cash=1000, deposits=5000, stocks=2000, bonds=1000,
        housing_self=30000, housing_investment=0, consumer_durables=5000,
        # 人为制造错误: 总资产 = 43000, 总负债 = 24000, NW 应为 19000
        mortgage=20000, consumer_loan=3000, other_debt=1000,
    )
    # 手动修改使不平衡
    bs.deposits = 9999  # 凭空多了 4999
    
    state = MagicMock()
    state.balance_sheets = {'households': bs}
    
    errors = validate_sfc(state)
    assert len(errors) > 0
    assert any('households' in e for e in errors)
```

### 9.3 第一个 e2e 测试示例

```python
# tests/integration/test_e2e.py
import pytest
from financial_sim.core import Simulation

@pytest.mark.integration
def test_run_12_months_baseline():
    """跑 12 个月 baseline 场景，无 SFC 违反"""
    sim = Simulation(
        config_path='scenarios/baseline.yaml',
        seed=42,
    )
    sim.run(n_ticks=12)
    
    # SFC 校验
    assert len(sim.sfc_violations) == 0, f"SFC violations: {sim.sfc_violations}"
    
    # 宏观变量在合理范围
    state = sim.state
    assert state.t == 12
    assert state.real_gdp > 0
    assert -0.10 < state.inflation_yoy < 0.30
    assert 0.0 <= state.unemployment_rate <= 0.30

@pytest.mark.integration
def test_run_24_months_macro_stable():
    """24 个月后宏观变量稳定"""
    sim = Simulation(config_path='scenarios/baseline.yaml', seed=42)
    sim.run(n_ticks=24)
    
    state = sim.state
    # GDP 增长应为正（小正值）
    gdp_growth_12mo = state.real_gdp / state.real_gdp_history[0] - 1
    assert -0.30 < gdp_growth_12mo < 0.50
```
