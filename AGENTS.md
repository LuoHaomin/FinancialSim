# AGENTS.md — FinancialSim

教学型 ABM 宏观经济仿真器。Python 3.12 (uv) ABM 内核 + FastAPI UI 服务 + Svelte 5/TS/Vite 前端。
**核心约束**:每笔钱在两个部门必须有对手方(SFC 校验) — 这是改动任一资金流前必须先想清楚的事。

---

## 1. Layout

```
financial_sim/           # Python 包 (uv 管理)
  core/                  # simulation / state / step (tick 编排, ~2200 行)
  agents/                # household / firm / bank / cb / gov / ib / am
  markets/               # goods / labor / housing / credit / bonds / stocks
  monetary/              # 5 个 BS dataclass + SFC 校验器
  simulation/            # rng(命名流) / events(ShockEvent) / snapshot
  ui_service/            # FastAPI: registry + projection + main
  config.py              # SimConfig (pydantic BaseModel)
  scenarios.py           # YAML 加载 → (SimConfig, EventManager)
frontend/                # Svelte 5 + TS + Vite + ECharts (独立 npm)
scenarios/*.yaml         # 7 个预设场景 (baseline / crisis_2008 / stagflation …)
tests/{unit,integration,calibration}/
docs/                    # 设计文档; docs/AGENTS.md 是**主体层设计**,别和本文件混
IMPLEMENTATION.md        # 实现总账:Phase 进度 + 记账规格(改前必读 §4) + 校准记录(§5)
DESIGN.md                # 顶层设计
```

---

## 2. Commands

### Backend (Python, uv)

```bash
uv sync --extra dev                # 安装依赖 (Python 3.12)
uv run pytest -q                   # 全量测试 (~14s)
uv run pytest tests/unit/ -q       # 快速子集 (~数秒)
uv run pytest tests/integration/ -q
uv run pytest tests/calibration/ -q    # 慢 (蒙特卡洛 stylized facts)
uv run pytest tests/integration/test_performance.py -q   # 性能门禁
uv run pytest -k TestScenarioLoader    # 按测试类名/文件名筛
uv run ruff check .                # lint (CI 必须绿)
uv run mypy financial_sim/         # typecheck (CI 宽松, continue-on-error)
```

`addopts` 强制 `-v --tb=short --strict-markers --strict-config -ra`,warnings 升级为 error(除 numba/pandas 弃用警告)。

### Frontend (Svelte)

```bash
cd frontend
npm install
npm run dev                        # http://localhost:5173 (代理 /api → :8000)
npm run check                      # svelte-check + tsc (CI 不跑,本地走)
npm run build                      # 产物 frontend/dist/
```

### 全链路 UI 实测(需 dev 服务先起)

```bash
# 终端 1
uv run uvicorn financial_sim.ui_service.main:app --port 8000
# 终端 2
cd frontend && npm run dev
# 终端 3 (可选 e2e 冒烟)
python frontend/tests/e2e_smoke.py        # 默认 http://localhost:5173/
```

---

## 3. Architecture — 必须先理解的契约

### 3.1 SFC (Stock-Flow Consistency) 是地基
所有跨部门资金流(`_pay_wages`、`_bank_cycle`、`_government_cycle`、`_bond_cycle`、`_consumer_credit_cycle` …)必须在 `core/step.py` 内**双边镜像记账**。违反 = 钱凭空产生/消失 = 仿真失效。

校验器:`financial_sim/monetary/sfc.py:validate_sfc()`(9 项跨部门检查,相对容差 `1e-9·scale`)。
每次 `monthly_tick` 末尾跑一次;违反写到 `state.sfc_violations`(**不抛异常**,需查 meta 数值)。

**历史 bug 高发模式**:任一负债变化必须对应资产或资本变化(LOlr 抹平资本、同业违约单边核销、利息资本化漏记收入)。改 `step.py` 前先在 `IMPLEMENTATION.md` §4 找到对应里程碑的记账规格。

### 3.2 单银行 / 多银行的"主银行"语义
- `state.bank == state.banks[0]`(同一个实例,不是副本)。多银行初始化时 `interbank_network = None`(`core/simulation.py` 注释明确说明:Phase 3 Week E 前**禁止**依赖 n_banks > 1 的同业敞口)。
- 部门聚合资金流(工资/消费/政府/税收)**只**记在 `state.bank`,外围银行 `reserves=0`。多银行场景的 SFC 验证在 `build_balance_sheets` 现场求和。
- `state.firm` 是 `firms[0]` 的只读 property(向后兼容别名);聚合资金流必须逐企业记账,不要用它求和。

### 3.3 Tick 编排顺序是 load-bearing
`monthly_tick` 的步骤顺序在 `core/step.py` 有大量"为什么不能换"的注释(发薪在收入回款之后、生产先于消费、付息先于发债等)。**不要重排**;新增子循环必须挂在明确位置并写注释说明。

### 3.4 可复现性:命名 RNG 流
所有随机抽样必须走 `RNGManager.stream("name")`,流名是稳定字符串(常用:`"household_init"`、`"pricing"`、`"stocks"`、`"credit_denials"`、`"cross_holdings"`)。**禁止**:
- `np.random.random()` / `np.random.default_rng()` 无命名
- Python `hash()` / `id()` 作种子(`rng.py:_stable_hash` 是专用实现)

同 seed + 同干预 → 逐 tick 字节级一致(`tests/integration/test_ui_api.py` 锁这条性质)。

---

## 4. Feature Flags(默认值容易踩坑)

`SimConfig` 里以下模块默认 **OFF** — 想用必须显式开启:

| Flag | Default | 备注 |
|---|---|---|
| `enable_bond_market` | False | P0-b 已实现但默认关;开启后 `_bond_cycle` 接管赤字融资 |
| `enable_consumer_credit` | False | P0-a 配给 + 还款循环 |
| `enable_stock_market` | False | Week C Brock-Hommes |
| `enable_cross_holdings` | False | Week C-M3 交叉持股 |
| `enable_investment_bank` | False | Week D,需先开股票市场 |
| `enable_asset_manager` | False | Week D |
| `enable_supply_chain` | False | Week E-M1 IO 中间品 |
| `enable_events` | True | ShockEvent 网关 |
| `enable_default` | True | 企业违约检测 |
| `enable_housing` | True | Phase 2 房产 |
| `enable_firm_dividends` | True | Week B |
| `enable_bank_dividends` | True | 校准后稳态修复用 |
| `enable_interest_on_reserves` | True | IOR 通道,缺失会触发机械性"窄银行危机" |

---

## 5. Style & 约定

- **中文 inline 注释 OK**(`pyproject.toml` per-file-ignores 显式允许 `ERA001`、`E741`)。
- 测试文件允许 `B011` 断言、`E741` 单字母变量、注释代码。
- `__init__.py` 允许 re-export(F401 忽略)。
- **绝不在 `step()` 写 `print()`** — 用 `get_logger(__name__)`,命名空间 `financial_sim.*`(`utils/logging.py:setup_logging`)。
- ruff 规则集:E/W/F/I/N/UP/B/C4/RET/SIM/TID/PT/ERA。**忽略**:E501(行长)、B008(pydantic 默认参数)、SIM108(三元)。
- 不要把 `data/`、`snapshots/`、`reports/*.parquet` 等塞进仓库 — `.gitignore` 已排除,路径工具在 `utils/paths.py`。

---

## 6. Testing

- `tests/conftest.py` 提供 `default_config`、`small_config`(10 HH, 12 ticks)、`project_root_path`、`scenarios_path` fixture。
- 测试类名 `Test*`、函数 `test_*`(pytest 强制)。
- 性能门禁:`tests/integration/test_performance.py` 断言 `n_ticks=5000` P95 tick < 2s — CI 必跑。
- SFC 违反计数:`sim.state.sfc_violations` 是 `list[list[str]]`(每 tick 一组错误),UI 用 `sum(len(v) for v in state.sfc_violations)`。
- 场景回归门禁:`scenarios/crisis_2008.yaml`(seed=7,4 个 preset)+ `tests/integration/test_crisis.py`。任何重构改前先跑 baseline + crisis 60 月,确认零 SFC 违反。

### 写新测试前
1. 单元函数/记账 → `tests/unit/`,每个 SFC 校验配一个**负向测试**(故意构造违反)。
2. 跨子循环 / 阶段验收 → `tests/integration/`。
3. 蒙特卡洛 / 矩匹配 → `tests/calibration/`(慢,本地默认跑,CI 跑)。

---

## 7. UI 服务层规则(只读投影 + 唯一写通道)

`financial_sim/ui_service/` 严格执行三条铁律(详见 `docs/FRONTEND_DESIGN.md §0`):
1. **状态从 `projection.py` 投影** — 不暴露任何 agent 引用给前端;REST/WS 输出全是 dict/list/标量。
2. **干预只经 `/api/sims/{id}/interventions` 走 ShockEvent 网关** — 禁止 UI 层直写 agent 字段。
3. **同 seed 同干预必逐位复现**(`test_ui_api.py` 锁)。

`SimulationRegistry` 后台线程逐 tick 推;`MAX_SIMS=8`,`IDLE_SIM_TTL_SECONDS=30min`(暂停超时自动回收)。
WS 帧含 `macro` + `events_fired` + `sfc_violations` 计数。

---

## 8. CI

`.github/workflows/calibration.yml`(push main / 触及 `financial_sim/**`、`tests/**`、`pyproject.toml` 时):
- Ubuntu + macOS × Python 3.12
- `uv sync --extra dev` → `ruff check .` → `mypy financial_sim/`(宽松)→ `pytest tests/unit/ --cov` → `pytest tests/integration/`
- coverage 上传 codecov(ubuntu only)

提交前必须本地通过:`ruff check .` + `pytest -q`。

---

## 9. 改动前 checklist

1. **改 `core/step.py` 任一资金流** — 先在 `IMPLEMENTATION.md` §4 找对应里程碑的记账规格,写双边镜像;配套负向测试。
2. **新增 agent / 字段** — 必须:
   - 加进 `agents/<file>.py` dataclass
   - 加进 `monetary/balance_sheets.py` 对应 BS 类
   - 在 `monetary/sfc.py` 加跨部门一致性检查(任一银行资产 ↔ 对手方负债)
   - 在 `state.build_balance_sheets()` 现场求和
3. **改 SimConfig 字段** — `pyproject.toml` pydantic Field 约束 + 默认值同步;`scenario_loader` 的负向测试要保持绿。
4. **改 frontend** — 不要破坏 vite proxy(`/api` → `127.0.0.1:8000`);WS 帧结构变 → 同步改 `frontend/src/lib/api.ts` + `stores.ts`。
5. **新增场景** — `scenarios/<name>.yaml` + `list_scenarios()` 自动收录;触发偏移用 `trigger_offsets: [...]` 显式声明。

---

## 10. 文档地图(按需读)

| 想了解什么 | 读哪里 |
|---|---|
| 整体设计 | `DESIGN.md` |
| 进度总账 / 记账规格 / 校准记录 / 残留限制 | `IMPLEMENTATION.md` |
| 主体字段与行为 | `docs/AGENTS.md`(注意:这个文件是**领域设计**,不是 agent meta-doc) |
| 市场机制 | `docs/MARKETS.md` |
| 货币 + SFC | `docs/MONETARY.md` |
| 调度 + 可复现 | `docs/SIMULATION.md` |
| 校准目标 | `docs/VALIDATION.md` |
| 预期形成 | `docs/EXPECTATIONS.md` |
| 前端架构 / WS 协议 | `docs/FRONTEND_DESIGN.md` |
| 前端使用说明 (启动/视图导览) | `frontend/README.md` |
