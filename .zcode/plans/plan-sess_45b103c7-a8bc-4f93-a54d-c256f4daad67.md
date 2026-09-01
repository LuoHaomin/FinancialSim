# 前端 & 前后端连接层全面升级方案

目标：把 MVP 升级为对齐 `docs/FRONTEND_DESIGN.md` 的完整实现——WS 实时协议为数据主通道、四层下钻（L1 宏观 / L2 部门 / L3 资产负债表 / L4 网络图）、丰富的数据投影与现代化视觉。三条铁律（只读投影 / 干预走 ShockEvent / 同 seed 逐位复现）不变。

## Phase A — 后端投影层扩展（ui_service/projection.py + main.py，只读，不动内核）

A1. **扩展时序**：`series()` 暴露全部 MacroSnapshot 字段（nominal_gdp, avg_wage, total_consumption, total_output, price_level, output_gap）+ 修复 housing_price 尾部切片对齐的脆弱性（改为统一以 t 为键合并）。
A2. **部门资产负债表端点** `GET /api/sims/{id}/sectors`：调用现成的 `state.build_balance_sheets()`，输出 7 部门 Godley 存量-流量矩阵（含 SFC 校验状态）。
A3. **家庭部门端点** `GET /api/sims/{id}/households?stats=dist`：服务端聚合分布（财富/收入五分位、Gini、住房自有率、按揭违约压力、失业时长分布），不暴露逐 agent 引用，仍符合铁律 1。
A4. **政府/央行端点** `GET /api/sims/{id}/agents/government|central_bank`：财政（债务/税收/支出/转移）与货币（准备金/基础货币/LtR）面板数据。
A5. **网络图端点** `GET /api/sims/{id}/network/{interbank|cross_holdings}`：邻接矩阵 → 节点/边列表（权重=敞口），节点附带关键属性（capital、car）。
A6. **危机遥测** `GET /api/sims/{id}/stress`：fire_sale_pressure、housing_expectations_factor、failed_banks、cumulative_default_units、银行 CAR 分布。
A7. **元数据端点** `GET /api/meta`：返回场景列表（含名称/描述）+ 冲击预设清单，消灭前端硬编码副本。
A8. **SFC 详情** `GET /api/sims/{id}/sfc`：暴露逐 tick 违反文本（现在只有计数）。
A9. 每个新端点配 integration 测试（挂进 `tests/integration/test_ui_api.py` 风格），并验证同 seed 逐位复现不破。

## Phase B — 前端连接层重构（stores + api）

B1. **WS 为主通道**：实现协议 v1 全部下行帧（tick / intervention_ack / ack）+ 上行命令（set_speed / pause / step / run_to），tick 帧驱动 store 增量更新；REST 仅做启动回填（series?from_t）与断线重连兜底（带指数退避的自动重连）。
B2. **api.ts 重构**：场景/预设改为 `GET /api/meta` 拉取；统一错误解析（FastAPI 422/409 detail 提取）→ 用户可读错误对象；全端点 typed。
B3. **store 拆分**：按 `src/lib/stores/` 目录拆 sim/control/series/agents/shock 模块，删除死掉的 `paused` store；补 flush-on-destroy。

## Phase C — UI 重构（视觉 + 交互 + 新视图）

C1. **设计系统**：重写 app.css（删模板残留），统一深色金融终端风格：色板、字体层级、卡片/表格/徽章组件化（`components/ui/`）；SFC 违规从角落徽章升级为顶部全局警报条（可点开看详情）。删除 Counter.svelte、.DS_Store、dist 提交残留。
C2. **L1 宏观面板重做**：KPI 卡片行（GDP、失业、通胀、政策利率、房价 + 新增名义 GDP/产出缺口）+ 主图（dataZoom 缩放、悬停 tooltip、markLine 悬停显示冲击完整参数、系列点选）；副图区：部门 BS 矩阵热力视图 / 压力遥测仪表 / 房市面板（房价+租金+成交量）。
C3. **L2 部门下钻全量**：tab 扩为企业（分页+排序+搜索+破产筛选）/ 银行 / 家庭（分布统计 + 分位数图表）/ 政府 / 央行 / 部门矩阵；表格行内 sparkline。
C4. **L3 详情**：补 12 个月迷你走势（企业 deposit/debt、银行 CAR 等）、本月分录摘要字段。
C5. **L4 网络图**：引入 d3-force，同业敞口 + 交叉持股两个力导向视图（节点大小=规模、边宽=敞口、失败银行红色高亮）。
C6. **控制条升级**：速度滑条（0–60）、run_to 跳转、步进；干预面板用 meta 端点渲染预设（含描述）、自定义通道白名单下拉；toast 系统替代瞬时 ✓/✗ 文本；多实例管理列表（切换/关闭，新建不再泄漏旧实例）。
C7. **图表组件统一**：抽 `components/chart/` 封装 ECharts（响应式 store 驱动 setOption、增量 append、统一 dispose）。

## Phase D — 测试与验收

D1. e2e 冒烟升级：现有 `frontend/tests/e2e_smoke.py` 扩展覆盖新面板（部门矩阵/网络图/家庭分布/WS 连接状态）；接入 package.json scripts。
D2. `npm run check` + `npm run build` 全绿；`uv run pytest tests/integration/ -q` + `ruff check .` 全绿。
D3. 全链路手动验证（uvicorn + vite dev + e2e），确认 SFC 徽章、shock 闭环、同 seed 复现测试仍过。

## 顺序与提交策略

按 A → B → C → D 分 4 个 PR 级提交（`feat(frontend): …`），每个阶段结束跑回归。Phase C 内部按 C1 → C6 → C2 → C3/C4 → C5 顺序推进。不动 `core/`、`agents/`、`markets/`、`monetary/`（除 main.py 里纯投影相关的字段读取，如需要只加只读聚合函数）。

风险点：WS 驱动重绘性能（用增量 append + 节流）；1000 家庭聚合放服务端避免前端爆量；d3-force 新依赖（仅前端）。