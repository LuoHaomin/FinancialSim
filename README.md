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

**v0.2 设计已定型，进入 Phase 0 实现。**

| 阶段 | 状态 | 目标 |
|------|------|------|
| Phase 0 | 🚧 进行中 | SFC 内核 + 月度循环 + 最小主体（1-2 周） |
| Phase 1 | ⏳ 待开始 | 最小可工作核心（4-6 周） |
| Phase 2 | ⏳ 待开始 | 金融层扩展（4-6 周） |
| Phase 3 | ⏳ 待开始 | 完整经济（4-6 周） |
| Phase 4 | ⏳ 待开始 | 教学层（4-6 周） |
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
