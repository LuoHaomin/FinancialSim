# ABM 宏观经济仿真器：设计文档

> 版本：v0.2
> 状态：架构定型，待校准与实现
> 最后更新：2026-08-27

---

## 0. 阅读说明

本文档是 Agent-Based Macroeconomics（ABM）仿真器的顶层设计。
所有核心架构决策已定。

**文档结构**：

| 文档 | 内容 | 行数 |
|---|---|---|
| **DESIGN.md**（本文档） | 项目概述、架构决策、技术栈、路线图 | ~300 |
| [docs/AGENTS.md](docs/AGENTS.md) | 8 类主体、违约破产、人口学 | ~450 |
| [docs/MARKETS.md](docs/MARKETS.md) | 4 类市场、价格指数、通胀预期 | ~350 |
| [docs/MONETARY.md](docs/MONETARY.md) | 货币架构、SFC 会计内核、利率传导 | ~350 |
| [docs/EXPECTATIONS.md](docs/EXPECTATIONS.md) | Brock-Hommes、多资产预期机制 | ~200 |
| [docs/SIMULATION.md](docs/SIMULATION.md) | 时间调度、性能、可复现性、事件系统 | ~450 |
| [docs/VALIDATION.md](docs/VALIDATION.md) | 涌现目标、校准测试、学术对比 | ~250 |

**标记约定**：
- ✅ 已决定
- ❓ 待讨论/未定
- ⚠️ 风险/陷阱提示
- 🆕 v0.2 新增/修正

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
│         主 tick = 1 个月 │ 内含 20-30 个日级快循环      │
└────────────────────────────────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
   ┌─────────┐       ┌──────────┐       ┌──────────┐
   │ Agents  │       │ Markets  │       │  State   │
   │  8 类   │ ◄───► │  混合出清  │ ────► │ Timeseries│
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
| 3 | **Agent 集** | 8 类（企业多部门、银行双层、家庭个体、CB、政府、外资） | 现代经济结构 |
| 4 | **货币架构** | 外生基础货币 + 内生信用创造 | 后凯恩斯主流 |
| 5 | **资产价格频率** | 日级高频 | 充分涌现金融现象 |
| 6 | **危机触发** | 完全内生 | 涌现式，非剧本 |
| 7 | **市场出清** | 混合（商品灵活 + 劳动粘性 + 信贷配给） | 新凯恩斯 |
| 8 | **预期机制** | 按资产类别选择（股票 BH / 房产锚定 / 债券期限结构） | 真实市场结构 |
| 9 | **生产** | 6 部门 + CES 生产函数 + 资本折旧 | 现代产业结构 |
| 10 | **家庭粒度** | 个体级（N = 10K–100K） | 帕累托尾能涌现 |
| 11 | **网络** | 每层不同拓扑 + 自适应信贷（关系贷款 + 粗筛） | 真实金融体系 |
| 12 | **政策** | Taylor 默认 + 手动覆盖；财政/审慎完全可调 | 教学最大化 |

### 2.3 v0.1 → v0.2 变更摘要

| 变更 | 位置 | 说明 |
|---|---|---|
| SFC 资产负债表拆分 | MONETARY.md 5.3.1 | 1 个类 → 5 个独立类 |
| 工资议价修正 | MARKETS.md 4.2.1 | 修复 bool/双重计价/利润率语义 |
| 抵押品容量修正 | MARKETS.md 4.4.2 | `(1-ltv)` → `ltv` |
| 货币守恒修正 | MONETARY.md 5.3.3 | 加入企业存款 |
| 新增：资本折旧 | AGENTS.md 3.3.3 | 部门异质折旧率表 |
| 新增：违约破产 | AGENTS.md 3.10 | 触发条件 + 损失分配 + 处置流程 |
| 新增：银行利润循环 | AGENTS.md 3.4.3 | 顺周期利润→资本→信贷 |
| 新增：利率传导 | MONETARY.md 5.4 + AGENTS.md 3.4.2 | 完整传导链 + 时滞表 |
| 新增：通胀预期 | MARKETS.md 4.6 | 按主体类型异质 + 脱锚机制 |
| 新增：事件系统 | SIMULATION.md 8.3 | 冲击定义 + 预设库 + 注入点 |
| 新增：稳态初始化 | VALIDATION.md 13.2 | 反向推算 + burn-in |
| 修正：测试用例 | VALIDATION.md 12.3.1 | Pareto 尾计算逻辑 |
| 修正：PerfMonitor | SIMULATION.md 8.6 | 构造函数 + summary |

---

## 3. 技术栈 ✅

| 层 | 选型 | 理由 |
|---|---|---|
| **仿真核心** | Python 3.11+ | 迭代速度 >> 运行速度 |
| 数值计算 | NumPy + Numba（JIT 热点） | Numba 对循环可 10-100x 加速 |
| 数据表 | Polars | 列式，向量化，快 |
| 网络/稀疏 | SciPy.sparse + NetworkX | 标准 |
| **状态持久化** | Parquet（快照）+ DuckDB（查询） | 教学项目首选 |
| **可视化层** | Svelte + WebSocket | 下钻 UI 天然适合 DOM |
| 图表 | ECharts | 时间序列 + 网络 |
| **测试** | pytest + calibration suite | 见 VALIDATION.md |
| **CI** | GitHub Actions | 跑校准测试 |

**不选 Rust/Godot/Unity 的理由**：
- 迭代速度优先
- 教学项目重视可读性
- 性能瓶颈用 Numba + 向量化解决

---

## 4. MVP 路线图

### Phase 0：原型（1-2 周）
- 单部门 + 代表性 HH
- 验证 SFC 守恒
- 跑通月度循环

### Phase 1：最小可工作核心（4-6 周）

| 组件 | 包含 | 说明 |
|---|---|---|
| 部门 | 3 部门（消费品 / 资本品 / 服务） | 简化 CES |
| 主体 | 4 类（HH + Firms + Bank + CB） | 个体级 HH |
| 家庭 | 1K-5K | Layer A only |
| 股市 | Brock-Hommes 7 规则 | 日级 |
| 债市 | 期限结构 | 简化 |
| SFC | 完整 5 部门校验 | 每月强制 |
| 违约 | 企业 + 家庭 | 基础版 |
| 利率传导 | 完整链 | 策略率 → 贷款利率 |
| 通胀预期 | 适应性 | 按主体异质 |
| 事件系统 | 基础 | 外生冲击注入 |
| 可视化 | matplotlib 6 图 | GDP/CPI/失业/股价/信贷/基尼 |
| 可复现 | RNG + 快照 + 重放 | Parquet |

### Phase 2：金融层扩展（4-6 周）
- 多家商业银行 + 投资银行
- Interbank core-periphery 网络
- 房产市场（独立机制）
- Fire-sale externality
- 银行顺周期利润循环
- 资管/保险赎回螺旋
- 危机涌现测试

### Phase 3：完整经济（4-6 周）
- 6 部门 + 完整 CES + 原材料投入
- 8 类主体齐全
- 自适应信贷网络（关系贷款优化）
- 供应链网络
- 交叉持股网络
- 场景库（2008、滞胀、战后复苏）

### Phase 4：教学层（4-6 周）
- 透明黑盒 UI（4 层下钻）
- 场景编辑器
- 实时干预界面
- 教程 / 引导任务

### Phase 5：校准与验证（持续）
- Calibration suite 完整化
- 与历史数据对比
- 教学实验

---

## 5. 待决事项

### 5.1 已部分决定但需细化

- [ ] 校准策略：美国数据 vs 中国数据？
- [ ] 初始年份：1950 / 1980 / 2000 / 2020？
- [ ] Burn-in 期长度：100 个月是否足够？
- [ ] 稳态初始化："风格化数值" vs 真实数据？
- [ ] Layer B 行为桶：桶定义与帕累托尾验证
- [ ] 人口学动态：MVP 静态 vs Phase 3 动态？

### 5.2 ❓ 完全未定

- [ ] 外资模块：是否实现？固定 vs 浮动汇率？
- [ ] UI 框架最终选型：Svelte vs React？
- [ ] 多语言支持：中文 / 英文？
- [ ] 部署方式：本地 / Web / 两者？

---

## 6. 版本历史

| 版本 | 日期 | 内容 |
|---|---|---|
| v0.1 | 2026-08 | 12 项架构决策完成，整体设计定型 |
| v0.2 | 2026-08 | 文档拆分为 6 个专题文件；修复 SFC 数据结构、工资议价、抵押品逻辑、货币守恒；新增违约破产、银行利润循环、利率传导、通胀预期、事件系统、资本折旧、稳态初始化 |

---

## 附录 A：术语表

| 术语 | 解释 |
|---|---|
| **ABM** | Agent-Based Modeling，基于主体的建模 |
| **DSGE** | Dynamic Stochastic General Equilibrium，动态随机一般均衡 |
| **CES** | Constant Elasticity of Substitution，固定替代弹性 |
| **SFC** | Stock-Flow Consistency，存量-流量一致性 |
| **TFPM** | Transaction Flow Matrix，部门间交易流量矩阵 |
| **CAR** | Capital Adequacy Ratio，资本充足率 |
| **LCR / NSFR** | Basel III 流动性指标 |
| **NPL** | Non-Performing Loan，不良贷款 |
| **LTV** | Loan-to-Value，贷款价值比 |
| **DTI** | Debt-to-Income，债务收入比 |
| **ICR** | Interest Coverage Ratio，利息覆盖倍数 |
| **NAIRU** | Non-Accelerating Inflation Rate of Unemployment，自然失业率 |
| **MPC** | Marginal Propensity to Consume，边际消费倾向 |
| **Taylor Rule** | 央行利率设定规则 |
| **Stiglitz-Weiss** | 信贷配给理论 |
| **Minsky Moment** | 明斯基时刻：投机性融资崩溃 |
| **Financial Accelerator** | 金融加速器：Bernanke-Gertler-Gilchrist |
| **Debt-Deflation** | 债务-通缩螺旋：Fisher |
| **Brock-Hommes** | 异质信念资产定价模型 |
| **Fire-Sale** | 资产被迫抛售导致的价格外溢效应 |
| **OMO** | Open Market Operations，公开市场操作 |
| **LOLR** | Lender of Last Resort，最后贷款人 |
| **UIP** | Uncovered Interest Parity，非抛补利率平价 |
| **GARCH** | Generalized AutoRegressive Conditional Heteroskedasticity |
| **Core-Periphery** | 核心-外围网络结构 |
| **Scale-Free** | 度分布服从幂律的网络 |
| **stylized facts** | 经验中反复出现的统计规律（定性重现即可） |

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
2. **Caiani et al. (2016)** "Agent-based-stock flow consistent macroeconomics"

### B.3 危机机制与 Fire-Sale

1. **Minsky (1992)** *The Financial Instability Hypothesis*
2. **Brunnermeier, Pedersen (2009)** "Market liquidity and funding liquidity" *RFS*
3. **Cifuentes, Ferrucci, Shin (2005)** "Liquidity and risk management" *BIS*
4. **Gertler, Kiyotaki (2010)** "Financial intermediation and credit policy"
5. **Diamond, Rajan (2011)** "Fear of fire sales" *JFE*

### B.4 异质信念与资产定价

1. **Brock, Hommes (1998)** "Heterogeneous beliefs and routes to chaos" *JEDC*
2. **Hommes (2006)** "Heterogeneous agent models in economics and finance"
3. **LeBaron (2006)** "Agent-based computational finance"

### B.5 工资与菲利普斯曲线

1. **Taylor (1980)** "Aggregate dynamics and staggered contracts" *JPE*
2. **Calvo (1983)** "Staggered prices in a utility-maximizing framework"
3. **Gali (2015)** *Monetary Policy, Inflation, and the Business Cycle*

### B.6 网络与系统性风险

1. **Battiston et al. (2012)** "DebtRank" *Sci Rep*
2. **Acemoglu, Ozdaglar (2011)** "Opinion dynamics and stubbornness"

### B.7 已有 ABM 宏观模型

1. **EURACE** (2011, EU-funded)
2. **CIRCUIT Model** (financial fragility)
3. **Markose GEC Model** (systemic risk)
4. **Popoyan, Napoletano, Fagiolo (2017)** "Bank regulation"