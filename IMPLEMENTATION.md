# ABM 宏观经济仿真器：实现总账

> 状态：Phase 0-2 ✅ / Phase 3 ✅ / Phase 4 MVP ✅ / **Phase 3.5 架构收尾 ✅**（PR-1..7 全部完成）
> 最后更新：2026-09-01
> 测试基线：439 passed · 1 xfail（组合再平衡横截面梯度，待重校准）· ruff clean · 回归矩阵零 SFC 违反
> 对应设计：[DESIGN.md](DESIGN.md) + [docs/](docs/)；前端方案 [docs/FRONTEND_DESIGN.md](docs/FRONTEND_DESIGN.md)
>
> 历史里程碑的逐周过程细节（Phase 0-3 逐日/逐周记录、3.5.A-F 实施方案原文）已压缩进本总账，
> 完整过程见 `git log -- IMPLEMENTATION.md`。

---

## 0. 进度总账

### Phase 3.5 — 完整架构收尾（2026-08-28 ~ 09-01，全部完成）

> 动机：多个 xfail 的根因是"架构未收尾"而非"参数未校准"。先把架构全部铺开，最后一次性校准。

| PR | 状态 | 内容 |
|---|---|---|
| PR-1 多部门多家企业 | ✅ | `n_firms_per_sector` 从死代码生效；默认 1 向后兼容（决策：旧默认 50 与 `state.firm` 别名/老测试冲突，改回 1，需多企业时显式设置）；`tests/integration/test_multifirm.py` |
| PR-2 多银行 init | ✅ | `home_bank_id`（HH+firm，`"bank_assignment"` 命名流一次性分配）+ `market_share`（deposit-weighted）+ `_allocate_share` 工具；14 新测试 |
| PR-3 多银行 step 拆分 | ✅ | `pay_wages`/`consumption`/`gov_cycle`/`bank_cycle`/`housing`/`default+dividend+mortgage_default` 全部按 `home_bank_id` 镜像；init 同步拆 deposit+reserve+loan+mortgage；单银行保持主银行语义快路径 |
| PR-4 同业动态化 | ✅ | `InterbankNetwork.rewire()` 季度重连（按 CAR 重排核心）；多银行 init 自动启用网络；`rebalance_reserves` 暂禁用（跨银行 per-bank BS 不平衡，见残留 #4） |
| PR-5 NBFI 全开 | ✅ | 7 个 flag 默认开 + 5 处 SFC 修复（见 §4 记账规格）；行为验收测试曾钉住各 Phase 模块组合，PR-7 后解除 |
| PR-6 回归矩阵 | ✅ | `tests/integration/test_regression_matrix.py`：7 场景 × 3 种子 = 63 用例，零 SFC + 矩有限性 + golden 逐位锁定。**行为有意变更时必须显式重采 golden** |
| PR-7 失真分析 | ✅(第一期) | 供应链冷启动死亡螺旋修复（见 §5 校准记录 #1）；labor/multifirm/multisector/stock 验收测试解除钉住、全开通过 |

**Phase 3.5 之前的阶段速览**：

| 阶段 | 交付 |
|---|---|
| Phase 0 | 脚手架、SFC 内核、5 主体、月度 tick、商品/劳动市场、性能测试 |
| Phase 1 | RNGManager 命名流、异质性分布、永久收入消费、Taylor 央行、政府预算、通胀预期、快照/重放 |
| Phase 2 | 房产/抵押/NPL→REO→fire-sale、多银行(主银行语义)+同业敞口、银行失败处置、2008 危机全链路涌现 |
| Phase 3 | P0-a/b/c 前置(消费贷/债市/场景库)、Week A 多部门+CES+投资实流、Week B 动态劳动需求+疤痕+G 实流、Week C Brock-Hommes+组合选择+交叉持股、Week D 投行+资管+FSIC、Week E-M1 供应链 IO、Week F 场景库扩到 7 个 |
| Phase 4 MVP | `ui_service/`（只读投影 + 干预网关 + WS）+ `frontend/`（Svelte5 宏观看板 + 部门下钻）；W5 网络视图/W6 场景编辑器延后二期 |

### 当前残留与已知限制（按优先级）

1. **log-wealth 分布再校准**：债券市场默认开后 log-wealth 偏度 -0.83 → -1.1~-1.5。机制：赤字强制家庭认购国债 = 流动性再分配，痛集中在低存款户（需求收缩的收入损失也在底部）。已试"降低家庭认购份额"与"流动性缓冲保护"两个修法均无效，需专项设计（候选项：付息融资/期限结构/财政规则）。校准套件因此仍钉在核心体制。
2. **stagflation 场景全灭**：场景未配 `sectors` → 默认单企业经济，扛不住能源+工资冲击（HEAD 全关下也死，既有问题）。修法方向：场景 YAML 配多部门。
3. **冲击对 real_gdp 钝化**：财政/货币冲击通道本身生效（乘数、房价、银行失败均验证），但 real_gdp 几乎不动。HEAD 既有，非 PR-5 回归；与 #1 同属分布/动态再校准课题。
4. **跨银行 per-bank BS 不平衡**：`rebalance_reserves` 暂禁用（PR-4 遗留）。
5. **Week-C 组合再平衡横截面梯度**：高偏好群体受现金/供给双约束，xfail 标注中。
6. 其他既有简化：CB 持债利息滚入本金（利润上缴部分建模）；存款单一聚合利率；同业敞口 init 挂起项已由 PR-4 关闭。

---

## 1. 指导原则

| 原则 | 说明 |
|---|---|
| **SFC 优先** | 任何资金流必须双边镜像记账，经 `monetary/sfc.py` 校验。校验是地基，不能事后补 |
| **可复现优先** | 随机数一律走 `RNGManager` 命名流；魔术常量一律配置化 |
| **聚合代理一律不用** | 只允许"现场求和视图"（`build_balance_sheets`）或真实主体本体，不维护会漂移的副本 |
| **配置驱动** | 参数从 SimConfig/YAML 读，不写死代码 |
| **一次只动一组参数** | 校准顺序：结构性（份额/弹性）→ 行为性（MPC/风险偏好）→ 政策规则最后 |

反模式（禁止）：无 SFC 校验的资金流合并进 main；`np.random.random()` 等无命名 RNG；`step()` 内 `print()`；硬编码参数。

## 2. 现状结构

```
financial_sim/
  config.py                 # SimConfig (pydantic): 全部参数 (7 个 NBFI flag 默认开)
  core/                     # simulation / state / step (tick 编排, 全部记账镜像所在)
  agents/                   # household / firm / commercial_bank / government / central_bank
  markets/                  # goods / labor / housing / credit / bonds / stocks
  monetary/                 # balance_sheets (7 类 BS) / sfc (校验器, 相对容差)
  expectations/             # 通胀预期 (适应性+锚定+脱锚)
  network/                  # interbank (动态 rewire) / cross_holdings
  simulation/               # rng / events (ShockEvent) / snapshot (v5 JSON)
  ui_service/               # FastAPI: registry + projection + main (只读投影+干预网关)
  scenarios.py              # YAML 场景加载 → (SimConfig, EventManager)
frontend/                   # Svelte 5 + TS + Vite + ECharts
scenarios/                  # 7 个 YAML (baseline / crisis_2008 / stagflation / ...)
tests/{unit,integration,calibration}/
```

## 3. 测试策略

```
校准测试   ← 蒙特卡洛 stylized facts (tests/calibration/, 钉在核心体制)
集成/e2e   ← 回归矩阵、危机涌现、UI API (tests/integration/)
单元测试   ← 记账、行为函数、边界值 (tests/unit/)
```

| 原则 | 说明 |
|---|---|
| 每个 SFC 校验有负向测试 | 故意构造违反，验证能捕获 |
| 每个跨部门资金流双边镜像 | 写 step 函数前先写分录规格；配对两侧用同一数值变量 |
| 场景×种子回归门禁 | `test_regression_matrix.py` golden 锁定 + CI 的 baseline/crisis 门禁 |
| golden 变更纪律 | 行为有意变更 → 重采 golden 并在 commit message 说明；意外漂移 = bug |

## 4. 记账规格与教训（改资金流前必读）

**所有 SFC 记账 bug 都是同一类错误：一侧变动没有对手方。** 已知复发模式与对应规格：

| # | 模式 | 规格要点 |
|---|---|---|
| 1 | 债券发行/付息（`_bond_cycle`） | CB 持债只按实际承接的银行份额 `bank_amt` 入账（全额入账与 hh 持债双计）；hh 买债/收息必须镜像银行准备金（`bank.reserves` ↔ `cb.bank_reserves`）；CB 自持部分利息按"利润上缴"净零处理，不能走银行分支 |
| 2 | NBFI 与市场交易 | "市场池"不是账户——NBFI 必须与家庭部门直接对手成交（`_cross_trade_with_households` 双镜像）；强平/抛售同理，凭空记现金 = 银行 BS 违反 |
| 3 | 成交额截断 | helper 内 min 截断使实际成交 < 名义额 → 调用方必须用**返回的实际成交额**做镜像，不能用名义额 |
| 4 | 利息资本化 | 资本化的同时必须记收入（银行 A↑ 无 income → 资本缺口） |
| 5 | 破产/违约核销 | 债权资产减记必须有对手方（seized_assets / recovery 现金 / 资本冲减三边平衡） |
| 6 | 估值重估不入账 | 股价/房价波动本身不动存款；只有交易清算动账。严禁把浮盈变成购买力 |
| 7 | 双重融资 | 同一笔赤字只走一条融资通道（教训见残留 #1：货币化+私人认购并行 = 对家庭变相抽税） |

历史 bug 清单（Phase 0-2 已修复，详见 git log）：利息资本化漏记收入、LOLR 抹平资本、同业违约单边核销、快照别名分裂（bank vs banks[0]）、破产清算存款幽灵、REO 凭空蒸发、幻影购买、G 凭空注资不入销售账。

## 5. 校准与验证

### 校准记录（一次只动一组参数）

**#1 供应链冷启动死亡螺旋（PR-7 第一期, 2026-09-01）**
- 原值/症状：300 户全开经济首拍 u 40%（供应商零库存 → util=0 → 产出全额折减）；t=12 预热概念引入前 u_max 0.89
- 改动：① `io_warmup_months=12`（预热期照常采购但不折减产出）；② 产出折减按 IO 成本份额加权 `eff_util = 1 − share×(1−util)`（原 `eff_a = A×util` 硬折减使 10% 投入缺口清零产出）；Firm 新增 `io_input_share`
- 效果：u_end 0.42→0.00，gdp 112→325（全关基准 349）；labor/multifirm/multisector/stock 验收全开通过
- 副作用监测：回归矩阵 golden 无漂移（场景经济为单部门，无 IO 约束路径）

### Phase 5 校准与验证（持续运行）

| 工作流 | 内容 |
|---|---|
| 数据接入 | SCF 2019 + FRED（美）；CHFS 2019（中，需申请）。封装 `analytics/calibration_data.py`，离线缓存 `reports/data/` |
| 矩匹配 | 均值/波动/自相关/跨期相关；先网格搜索后 Nelder-Mead；自由参数 ≤20 |
| 回归门禁 | CI 跑 baseline + crisis；关键矩偏离 golden >25% 则 fail |
| 版本化报告 | 每次 release 生成 `reports/calibration_<date>.md` |

## 6. 附录：早期决策记录（Q1-Q12）

| # | 问题 | 采纳结果 |
|---|---|---|
| Q1 | 家庭异质性分布 | 截断正态(储蓄率/MPC) + LogNormal(工资/存款)；SCF 校准推迟 Phase 5 |
| Q2 | CES 部门参数 | stylized values；真实数据接入留 Phase 5 |
| Q3 | Taylor Rule | 惯性版，smoothing=0.85，下限 −0.5% |
| Q4 | 家庭数量 | 100-1000 起步；性能门禁 5000 |
| Q5 | BH 规则数 | 全部 7 条，配置可开关 |
| Q6/Q10 | 外资模块 | 不做 |
| Q7 | 债券期限结构 | 单一永久债起步（现状），期限分层见残留 #1 专项 |
| Q8 | 每 sector 企业数 | 默认 1 向后兼容（PR-1 决策）；多企业显式配置 |
| Q9 | BH 循环频率 | 日级子步 12/月，实测 ~7ms/tick 达标 |
| Q11 | Phase 4 技术栈 | FastAPI + Svelte 5，已交付 |
| Q12 | 校准数据 | 美国数据为主（FRED 免费），CHFS 双轨后置 |
