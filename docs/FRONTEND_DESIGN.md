# 前端设计方案（Phase 4：教学层）

> 状态：设计定稿 v1.1（2026-08-27），实现计划见 [IMPLEMENTATION.md](../IMPLEMENTATION.md) §6
> **已决策**（用户拍板 2026-08-27）：
> ① MVP 范围 = 实验模式的宏观看板+干预；教程课程延后；
> ② 单机自用，不做服务器/观众席部署；
> ③ 界面中文直出，i18n 不做键位。
> 对应设计：[DESIGN.md](DESIGN.md) + [SIMULATION.md](SIMULATION.md) + 快照格式 snapshot v5

---

## 0. 设计总纲

**一句话**：UI 是仿真的"只读投影 + 受控干预通道"，模型内核不因前端改动一行代码。

三条铁律（对应 IMPLEMENTATION.md §1 指导原则在 UI 层的投影）：

| 铁律 | 含义 | 违反的后果 |
|---|---|---|
| **只读投影** | UI 展示的一切状态都来自快照/时序接口，禁止前端持有或修改任何 agent 数据 | 内外两张账，仿真与展示漂移 |
| **干预即事件** | 用户一切操作（调利率、加税、触发冲击）都翻译为 `ShockEvent` 注入 EventManager，100% 落入 `shock_log` 可回放 | 教学场景不可复现 |
| **确定性优先** | 同 seed + 同干预序列 ⇒ 同一历史。断线重连/刷新页面必须能从快照恢复到同一世界 | 学生实验结果不可复验 |

## 1. 技术栈

| 层 | 选型 | 理由 |
|---|---|---|
| API 服务 | **FastAPI** + uvicorn | pydantic SimConfig 直接生成表单 JSON Schema；WebSocket/SSE 一等公民 |
| 数据序列化 | 服务器端 **Polars** 聚合 → JSON (REST) / Arrow IPC (大批量时序, 二期) | 与内核数据契约一致；避免前端做聚合计算 |
| 前端框架 | **Svelte 5 + TypeScript + Vite**（SPA） | 编译期优化适合高频 tick 推送；体积小 |
| 图表 | **ECharts**（宏观时序）+ **D3 force**（网络三视图） | 时序组件成熟；力导向图可定制 |
| 实时通道 | **WebSocket** 推 tick 增量；控制命令同通道上行（JSON 协议见 §4） | 单通道双向，教学场景并发规模小 |
| 状态管理 | Svelte store（tick 流 + sim meta 两棵树） | 无需引入重状态库 |
| e2e | **Playwright** 冒烟（加载→跑→干预→图表更新 四步） | 入 CI 防回归 |

## 2. 总体架构

```
┌─────────────────────────────────────────────────────┐
│ Browser (Svelte SPA)                                │
│  L1 宏观看板 → L2 部门/主体列表 → L3 单主体资产负债表 │
│  L4 网络图(同业/供应链/持股)   场景编辑器   教程课程  │
└───────────────▲─────────────────────┬───────────────┘
        WS tick流│                     │ REST/ interventions
┌───────────────┴─────────────────────▼───────────────┐
│ FastAPI 服务层 (ui_service/)                        │
│  SimulationRegistry: {sim_id → 后台线程 + ReplayMgr} │
│  ProjectionLayer: state → Polars → JSON Schema 视图  │
│  InterventionGateway: HTTP POST → ShockEvent 校验    │
│                       → EventManager (写 shock_log)  │
│  ⚠️ 服务层禁止直接改 agent 字段——只能构造 ShockEvent  │
└───────────────▲─────────────────────┬───────────────┘
                │ 内存调用 (同进程)     │ snapshot v5 读写
┌───────────────┴─────────────────────▼───────────────┐
│ financial_sim 内核 (不变): monthly_tick / EventManager│
│ / StateSnapshot / RNGManager                         │
└─────────────────────────────────────────────────────┘
```

- **SimulationRegistry**：每个打开的仿真 = 一个后台线程跑 `monthly_tick` 循环 + 可变速率/暂停。`sim_id` 为 ULID。
- **ProjectionLayer**：唯一允许读 state 的地方；输出物是 Polars DataFrame 的 JSON 投影 + pydantic 视图模型。
- **InterventionGateway**：把 REST 请求体校验成 `ShockEvent(name, channel, magnitude, trigger_t, duration)` 并注入——路径上不存在第二种改状态的方式。

## 3. 页面与信息架构（四层下钻）

### L1 宏观看板（默认页）
- ECharts 多折线：real_gdp、inflation_yoy、unemployment_rate、policy_rate、housing_price（可选开股票价格）
- 场景名 / seed / 当前 t / 播放速率 / 暂停·继续·单步 按钮
- shxock_log 时间轴标记（在每个冲击触发的 t 上打竖线，悬停显示参数）
- 关注区：SFC violations 计数徽标（恒应为 0，非 0 全局红色告警条）

### L2 部门与主体列表
- Tab: 家庭(聚合统计+分位数) | 企业(逐家) | 商业银行(逐家) | 政府 | 央行 | NBFI
- 表格列：主要存量/流量指标 + 迷你 sparkline（点击展开 L3）

### L3 单主体资产负债表
- 左右分栏：资产 vs 负债+净值；每行后缀该科目 12 月走势 sparkline
- 底部：本月分录摘要（由投影层从科目差分推导，非内核日志依赖）
- 家庭主体支持按 id 搜索（教学定位某一户破产过程）

### L4 网络图（D3 力导向，三视图切换）
- 同业网络：节点=银行，边宽=敞口（当前为静态骨架，Phase 3.5 E2 上线后显示动态敞口；冻结期边变虚线红色）
- 供应链网络：节点=企业，边=IO 购买额，断供时下游节点闪烁灰化
- 交叉持股：holder→issuer 有向图，边宽=持股价值（beta 图）；家庭部门作为单一外部大节点

### 场景编辑器 ⏸（二期, MVP 外）
- 表单 = `SimConfig.model_json_schema()` 自动生成 + 分组折叠
- 冲击编排器：从 PRESET_SHOCKS 选择预设 × 设 trigger_t/duration/magnitude override，时间轴拖拽排序
- "保存为 YAML"导出 scenarios/*.yaml 兼容格式

### 教程课程（3 门）⏸（延后, MVP 外）
每课 = 固定 seed + 预置场景 + 分步干预脚本 + "预期现象清单"核对卡：
1. 《通胀来了》：货币政策传导（加息→GDP 滞后回落→通胀收敛）
2. 《金融危机》：housing_bust 场景下观察抵押违约→fire-sale→救助
3. 《供给冲击》：stagflation 下理解滞胀为何让央行两难

## 4. WebSocket 协议（v1）

```jsonc
// 下行: 每 tick 一帧 (ProjectionLayer 生成)
{
  "type": "tick",
  "t": 42,
  "macro": {"real_gdp": 996.2, "inflation_yoy": 0.021,
            "unemployment_rate": 0.038, "policy_rate": 0.031,
            "housing_price": 118.4},
  "events_fired": [{"name":"tightening_50bp_6m","channel":"policy_rate"}],
  "sfc_violations": 0,
  "speed": 2.0           // tick/秒, 0=暂停
}
// 下行: 干预回执
{"type":"intervention_ack","id":"...","status":"accepted","shock_log_seq":17}

// 上行: 控制命令
{"cmd":"set_speed","value":4.0} | {"cmd":"pause"} | {"cmd":"step"}
{"cmd":"run_to","t":120}
```

REST 主要端点：

| 方法/路径 | 用途 |
|---|---|
| `POST /api/sims` | body=`{scenario?: string, config_yaml?: string}` → `{sim_id}`（自动后台起跑）|
| `GET /api/sims/{id}/series?keys=...&from=&to=` | 时序批量（Polars 投影）|
| `GET /api/sims/{id}/agent/{sector}/{agent_id}?t=` | L3 资产负债表视图 |
| `GET /api/sims/{id}/network/{view}?t=` | L4 三视图边表 |
| `POST /api/sims/{id}/interventions` | body=ShockEvent spec（Gateway 校验注入）|
| `GET /api/sims/{id}/interventions` | shock_log 只读审计表 |
| `POST /api/sims/{id}/snapshots` / `PUT .../{snap_id}` | 保存/加载快照 v5（续跑=ReplayManager）|

## 5. 关键机制

### 5.1 干预网关（唯一写通道）
```
POST interventions
  → pydantic 校验 (channel ∈ 已知枚举, magnitude 数值, trigger_t≥current_t)
  → 构造 ShockEvent, append 到 EventManager 待发队列
  → 返回 ack{shock_log_seq}
线程安全: EventManager 加锁; 同一 tick 内多干预按到达序编号
```
审计闭环：L1 时间轴上每根冲击线都可点开 `GET interventions` 里对应的原始请求体。

### 5.2 断线恢复 / 回放
- 服务端每 N ticks（默认 24）自动落一个内存检查点（snapshot v5 序列化的反序列化副本）
- 断线重连：客户端带 `last_t` 请求 `series?from=last_t` 补数据 + WS 重订阅
- 时间旅行（二期）：选中历史检查点 → fork 出新 sim_id 续跑（同一 check-point 可多世界对比）

### 5.3 大规模性能策略
- n=5000 家户不逐户推送：L2/L3 家庭层仅提供分位数视图与按需单户查询
- tick 帧只带宏观增量；明细全部走惰性 REST
- 100 并发只读连接目标：WS 广播一帧 O(连接数)，注册表读锁保护

## 6. 目录规划

```
financial_sim/ui_service/          # FastAPI 层 (Python, 新增)
├── main.py                        # app 工厂 + 静态托管 dist/
├── registry.py                    # SimulationRegistry + 后台线程
├── projection.py                  # state → Polars → JSON 视图
├── gateway.py                     # InterventionGateway
├── schemas.py                     # 视图模型 pydantic (tick_frame 等)
frontend/                          # Svelte SPA (新增)
├── src/lib/stores/                # tickStore / metaStore
├── src/lib/components/chart/      # MacroChart, Sparkline
├── src/lib/components/net/        # NetworkGraph (D3)
├── src/routes/dashboard|agents|agent/[id]|network|editor|learn/
└── tests/e2e/playwright.smoke.ts
tests/integration/test_ui_api.py   # FastAPI TestClient 冒烟 (不入 Playwright)
```

## 7. 非功能要求

| 项 | 目标 |
|---|---|
| API 延迟 | series/agent 视图 P95 < 200ms (n=5000) |
| tick 推送 | speed=8 tick/s 时端到端 < 150ms |
| 并发 | 100 只读连接不掉帧；写通道每 sim 串行 |
| 可复现 | 重放测试: 相同 seed+干预序列两次运行 macro_history 逐位一致 |
| CI | Playwright 冒烟 + UI API 测试进 GitHub Actions |

## 8. 未决问题（Q13+）

| # | 问题 | 建议 |
|---|---|---|
| Q13 | 时序大批量走 JSON 还是 Arrow IPC？ | MVP 用 JSON；n=5000×50 年全量拉取实测 >500ms 再切 Arrow |
| Q14 | 多仿真并存上限？ | 默认每进程 8 个 (内存换简单)；超限 LRU 淘汰并提示保存快照 |
| Q15 | 前端是否需要中文双语？ | **已决**: 中文直出, 不留 i18n 桩 |
| Q16 | 时间旅行 fork 对比是否进 MVP？ | 不进; 检查点机制先落地, fork 界面二期 |
| Q17 | 场景编辑器进 MVP 吗? | 不进; MVP 用预设场景下拉+参数覆盖 JSON 即可 |
