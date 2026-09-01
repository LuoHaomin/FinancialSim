# FinancialSim 前端使用说明

Svelte 5 + TS + Vite + ECharts + d3-force。数据一律来自后端只读投影，
干预一律经 ShockEvent 网关（三条铁律见 [docs/FRONTEND_DESIGN.md §0](../docs/FRONTEND_DESIGN.md)）。

## 启动

```bash
# 终端 1: 后端 (端口 8000)
uv run uvicorn financial_sim.ui_service.main:app --port 8000

# 终端 2: 前端 dev 服务 (端口 5173, /api 自动代理到 8000)
cd frontend && npm install && npm run dev
# 打开 http://localhost:5173/
```

常用脚本：

| 命令 | 作用 |
|---|---|
| `npm run dev` | dev 服务（HMR） |
| `npm run build` | 生产构建 → `dist/` |
| `npm run check` | svelte-check + tsc 类型检查 |
| `npm run e2e` | e2e 冒烟（需上面两个服务已在跑；uv 环境需 `uv pip install playwright && uv run playwright install chromium`） |

## 界面导览

顶部控制条：选场景 → **新建仿真** → 五个视图切换 + 播放控制。

| 视图 | 内容 |
|---|---|
| **宏观** | KPI 卡片（GDP/失业/通胀/利率/房价/工资）；主图支持缩放（滚轮/拖动 dataZoom）、悬停显示当月数值与冲击事件完整参数；消费/产出副图；金融压力遥测（fire-sale、CAR 分布、断供） |
| **部门矩阵** | 7 部门 Godley 存量-流量矩阵，行 = 科目、列 = 部门，尾部合计。任一部门 A ≠ L + NW 时净值亮红 —— 这就是 SFC 校验的可视化 |
| **家庭** | 财富/收入 Gini、五分位柱图、财富分布直方图、住房自有率、按揭断供压力（服务端聚合，每 8s 自动刷新） |
| **下钻** | 企业（搜索/排序/分页/隐藏破产）、银行、政府、央行四个 tab；点击企业/银行行展开 L3 资产负债表 |
| **网络** | d3-force 力导向图：同业敞口（节点=资本、边=敞口、蓝框=核心银行、红=失败）与交叉持股（需开 `enable_cross_holdings`）；悬停看详情 |

**播放控制**：▶/⏸/+1、速度滑条（0-30 tick/s）、"跳至"输入框 + `▶|` 快进到指定月（自动加速并在目标处暂停）。

**多实例**：后端允许 8 个并发仿真（`MAX_SIMS`）。创建第二个后控制条出现实例下拉，可随时切换；暂停实例 30 分钟不访问会被服务端自动回收。

## 干预（唯一写通道）

干预面板：预设下拉（描述来自 `/api/meta`）或勾选"自定义通道"（policy_rate / gov_spending / tax_rate / wage_shock / energy_price / housing_yield_target，强度 ∈ [-10,10]），设偏移月数与持续期后注入。注入即建 `ShockEvent`、到点在 tick 内触发，并记录到下方**冲击日志**（t/名称/通道/强度，可回放对照主图 markLine）。

SFC 违反 > 0 时顶部出现红色警报条，点击展开逐 tick 违反详情。

## 连接层行为

- WebSocket 为主通道（`/api/sims/{id}/ws`）：tick 帧驱动图表增量更新；断线自动重连（指数退避），期间 REST 轮询兜底，徽章实时显示 `WS 实时 / 断开·REST 兜底` 状态
- 同 seed + 同干预序列 → 曲线逐位一致（后端 `test_ui_api.py::TestDeterminism` 锁定）

## 目录

```
src/
  App.svelte                  # 外壳: 控制条 + 视图路由 + 干预 + 冲击日志
  lib/api.ts                  # 全端点 typed REST 客户端 + ApiError 解析
  lib/stores/connection.ts    # WS 主通道 + REST 兜底 + 播放命令
  lib/stores/toasts.ts        # toast 通知
  lib/AgentsView.svelte       # L2/L3 部门下钻
  lib/components/
    MacroPanel.svelte         # L1 宏观看板
    SectorsMatrix.svelte      # Godley 部门矩阵
    HouseholdsPanel.svelte    # 家庭分布
    NetworkView.svelte        # L4 网络图 (d3-force canvas)
    ChartFrame.svelte         # 响应式 ECharts 封装
tests/e2e_smoke.py           # Playwright 冒烟 (npm run e2e)
```
