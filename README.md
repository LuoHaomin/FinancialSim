# FinancialSim

> Agent-based macroeconomic simulation for education.

教学型 ABM 宏观经济仿真平台——SFC 记账内核保证每笔钱都有对手方，
让你亲手触发并观察真实经济机制（通胀、金融危机、滞胀、断供传导）。

## 当前状态

**Phase 0-3 全部完成；Phase 4 教学层 MVP 可用（宏观看板 + 政策干预）。**

| 阶段 | 状态 | 内容 |
|------|------|------|
| Phase 0-2 | ✅ 完成 | SFC 内核 + 月度循环 + 主体行为 + 房产/抵押/多银行/fire-sale |
| Phase 3 前置 | ✅ 完成 | 消费信贷 / 债券市场脚手架 / 场景库 |
| Phase 3 | ✅ 完成 | 多部门 CES / 动态劳动 / Brock-Hommes 股市 / 投行+资管 / 供应链 IO / 场景验收矩阵 |
| Phase 4 | 🚧 MVP 可用 | FastAPI 服务层 + Svelte 宏观看板 + 干预网关；网络视图/编辑器/教程为二期 |
| Phase 5 | ⏳ 待开始 | 校准与验证 (FRED/SCF 数据接入) |

测试基线：**341 passed · 1 xfail · ruff clean**；7 个场景 × 多种子零 SFC 违反。

## 快速开始

### 跑仿真 / 测试（后端）

```bash
brew install uv          # 如果还没有 uv
uv sync --extra dev      # 安装依赖 (Python 3.12)

uv run pytest -q         # 全量测试 (~14s, 341 个)
uv run ruff check .      # Lint
```

### 打开网页看板（前端）

终端 1 — 启动 API 服务:

```bash
uv run uvicorn financial_sim.ui_service.main:app --port 8000
```

终端 2 — 启动前端开发服务器:

```bash
cd frontend
npm install        # 首次需要
npm run dev        # → http://localhost:5173
```

浏览器打开 http://localhost:5173 :

1. 下拉选场景（基准 / 2008 危机 / 滞胀 / 房产泡沫破裂 …）→「新建仿真」
2. 宏观曲线实时滚动；▶ 继续 / ⏸ 暂停 / 单步 +1 控制节奏
3. 「政策干预」面板注入冲击（加息、财政紧缩…），曲线上出现冲击标记线
4. 「部门下钻」点开任意企业/银行的资产负债表
5. 每一次干预都进入底部**冲击日志**——可审计、可回放（同 seed 必复现）

### 生产模式构建（可选）

```bash
cd frontend && npm run build   # 产物 frontend/dist/
```

## 场景库

`scenarios/*.yaml`：基准、2008 危机、滞胀、房产泡沫破裂、战后复苏、
信贷紧缩、宽松信贷。每个场景 = SimConfig 参数覆盖 + ShockEvent 编排
（preset × trigger_offset），可直接在 API 里引用，也是教学实验的起点。

## 文档

- **[IMPLEMENTATION.md](IMPLEMENTATION.md)** — 实现总账：进度看板、各期取舍教训、Phase 4-5 计划
- **[docs/FRONTEND_DESIGN.md](docs/FRONTEND_DESIGN.md)** — 前端设计方案（架构 / 协议 / 页面）
- **[DESIGN.md](DESIGN.md)** — 顶层设计概述
- **[docs/](docs/)** — 专题设计
  （AGENTS 主体 / MARKETS 市场 / MONETARY 货币+SFC / EXPECTATIONS 预期 /
  SIMULATION 调度与可复现性 / VALIDATION 校准目标）

## 核心原则

1. **SFC 优先**——任何资金流动双边镜像记账，校验器逐 tick 把关（相对容差）
2. **确定性优先**——所有随机数走命名 RNG 流，同 seed + 同干预 ⇒ 同一历史
3. **UI 是只读投影**——干预唯一通道是 ShockEvent 网关，模型内核不因前端改动

## 许可证

MIT
