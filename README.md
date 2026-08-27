# FinancialSim

> Agent-based macroeconomic simulation for education.

教学型 ABM 宏观经济仿真平台——让你亲手触发出真实经济机制。

## 文档

- **[DESIGN.md](DESIGN.md)** — 顶层设计概述 + 12 项核心决策 + 路线图
- **[IMPLEMENTATION.md](IMPLEMENTATION.md)** — 实现计划（Phase 0-5 详细任务）
- **[docs/](docs/)** — 专题设计文档
  - [AGENTS.md](docs/AGENTS.md) — 8 类主体
  - [MARKETS.md](docs/MARKETS.md) — 4 类市场
  - [MONETARY.md](docs/MONETARY.md) — 货币架构 + SFC 会计内核
  - [EXPECTATIONS.md](docs/EXPECTATIONS.md) — 异质信念机制
  - [SIMULATION.md](docs/SIMULATION.md) — 时间调度、性能、可复现性
  - [VALIDATION.md](docs/VALIDATION.md) — 涌现目标 + 校准

## 当前状态

**Phase 0-2 已实现；Phase 3 前置批次（消费信贷 / 债券市场 / 场景库）进行中。**

| 阶段 | 状态 | 目标 |
|------|------|------|
| Phase 0 | ✅ 完成 | SFC 内核 + 月度循环 + 最小主体 |
| Phase 1 | ✅ 完成 | 最小可工作核心（主体行为 / 预期 / 违约 / 事件 / 快照） |
| Phase 2 | ✅ 完成 | 金融层扩展（房产 / 抵押 / 多银行 / 同业 / fire-sale） |
| Phase 3 前置 | 🚧 进行中 | 消费信贷、债券市场（私人持债）、场景库 |
| Phase 3 | ⏳ 待开始 | 完整经济（多部门 CES + 股市 + 投行/资管 + 网络动态） |
| Phase 4 | ⏳ 待开始 | 教学层（FastAPI + Svelte 四层下钻） |
| Phase 5 | ⏳ 持续 | 校准与验证 |

## 快速开始

```bash
# 安装 uv (如果还没有)
brew install uv

# 安装 Python 3.12 并创建 venv
uv python install 3.12
uv venv .venv --python 3.12
uv python pin 3.12

# 安装依赖
uv sync --extra dev

# 运行测试
uv run pytest tests/unit/

# Lint
uv run ruff check .
```

## 许可证

MIT
