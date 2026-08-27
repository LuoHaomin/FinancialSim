# 仿真引擎设计

> 返回：[DESIGN.md](../DESIGN.md)
> 版本：v0.2 | 2026-08-27

---

## 8.1 多尺度调度

```
主时钟：1 个月
快循环：每个主 tick 内 N=20-30 个日级 sub-tick
慢循环：人口、资本存量、技术按季度更新
```

---

## 8.2 Tick 内操作顺序

⚠️ **顺序敏感——同一月内的执行顺序直接影响模拟结果。**

```python
DAYS_PER_MONTH = 30


def monthly_tick(t):
    # ═══ 阶段 1: 日级快循环 ═══
    for day in range(DAYS_PER_MONTH):
        asset_market.step()           # 资产市场出清（股票、房产）
        interbank_market.step()       # 银行间拆借
        sentiment.update()            # 情绪/信心更新
        # 银行日内重新评估信用风险（可选）

    # ═══ 阶段 2: 月末决策更新 ═══
    form_inflation_expectations()    # 各主体更新通胀预期
    cb.set_policy_rate()             # CB 决策（Taylor Rule 或手动）
    banks.reprice_loans()            # 银行重新定价到期贷款
    firms.set_production_plan()      # 企业决定生产
    firms.set_prices()               # 企业调价（卡尔沃）
    firms.apply_depreciation()       # 🆕 资本折旧
    households.decide_consumption()  # 家庭消费决策
    households.decide_labor_supply() # 劳动供给
    households.decide_portfolio()    # 资产配置决策

    # ═══ 阶段 3: 月度市场出清 ═══
    goods_market.clear()             # 商品市场
    labor_market.clear()             # 劳动市场
    credit_market.clear()            # 信贷市场

    # ═══ 阶段 4: 违约与清算 ═══ 🆕
    resolve_defaults()               # 企业/家庭违约处理
    bank_profit_cycle()              # 银行利润与资本更新

    # ═══ 阶段 5: 月末统计 ═══
    aggregate_macros()                # 聚合宏观变量
    write_to_timeseries()             # 写入时序
    update_slow_vars()                # 更新慢变量（季度触发）
    validate_sfc(state)               # SFC 守恒校验
```

### 8.2.1 ⚠️ 关键陷阱

| 陷阱 | 说明 | 防范 |
|---|---|---|
| 顺序偏差 | 银行看到资产价格后再放贷 → 高估金融加速器 | 决策用上 tick 的价格，不用当期 |
| 快慢耦合 | 资产价格每月初重置，月末聚合到实体变量 | 日级循环只更新资产价格，不触发实体决策 |
| 事件时序 | 危机事件须有明确触发时刻 | 银行破产 = 日级事件，CAR 检查在利润结算后 |

---

## 8.3 事件与冲击系统 🆕

⚠️ **教学场景需要注入外生事件——石油危机、技术突破、政策实验。**

### 8.3.1 冲击定义

```python
@dataclass
class ShockEvent:
    """外生冲击事件"""
    name: str               # 事件名称（用于日志/教学展示）
    trigger_tick: int       # 触发时刻
    target: str             # 影响目标
    magnitude: float        # 冲击幅度（比例或绝对值）
    duration: int           # 持续月数（-1 = 永久, 1 = 单次）
    decay: float = 1.0      # 逐期衰减率（1.0 = 不衰减）

    def is_active(self, current_tick: int) -> bool:
        if self.duration == -1:
            return current_tick >= self.trigger_tick
        return (self.trigger_tick <= current_tick
                < self.trigger_tick + self.duration)

    def current_magnitude(self, current_tick: int) -> float:
        if not self.is_active(current_tick):
            return 0.0
        months_elapsed = current_tick - self.trigger_tick
        return self.magnitude * (self.decay ** months_elapsed)
```

### 8.3.2 预设冲击库

```python
PRESET_SHOCKS = {
    # ─── 能源危机 ───
    'oil_shock_1973': ShockEvent(
        name='1973 Oil Shock',
        trigger_tick=60,         # 第 5 年
        target='sector:energy.price',
        magnitude=2.0,           # 能源价格翻倍
        duration=12,             # 持续 1 年
        decay=0.92,              # 逐月衰减
    ),

    # ─── 货币政策实验 ───
    'volcker_rate_hike': ShockEvent(
        name='Volcker Rate Hike',
        trigger_tick=120,
        target='cb.policy_rate',
        magnitude=0.05,          # 加息 5%
        duration=-1,             # 永久
    ),

    # ─── 财政刺激 ───
    'fiscal_stimulus': ShockEvent(
        name='Fiscal Stimulus',
        trigger_tick=60,
        target='gov.gov_spending',
        magnitude=0.03,          # 政府支出增加 3% GDP
        duration=24,             # 持续 2 年
        decay=0.95,
    ),

    # ─── 技术突破 ───
    'tech_boom': ShockEvent(
        name='Tech Boom',
        trigger_tick=60,
        target='sector:high_tech.productivity',
        magnitude=0.20,          # TFP 提升 20%
        duration=-1,             # 永久
    ),

    # ─── 疫情冲击 ───
    'pandemic': [
        ShockEvent(
            name='Pandemic Supply Shock',
            trigger_tick=120,
            target='sector:services.labor_productivity',
            magnitude=-0.15,       # 服务业劳动生产率下降 15%
            duration=12, decay=0.9,
        ),
        ShockEvent(
            name='Pandemic Demand Shock',
            trigger_tick=120,
            target='households.consumption_propensity',
            magnitude=-0.10,       # MPC 下降 10%
            duration=18, decay=0.95,
        ),
    ],
}

# 用户也可手动创建:
# sim.schedule_shock(ShockEvent(name='Custom', trigger_tick=100,
#                                target='cb.policy_rate', magnitude=-0.02, duration=6))
```

### 8.3.3 冲击注入点

```python
def apply_shocks(state: 'SimulationState'):
    """在 tick 执行前应用所有活跃冲击"""
    for shock in state.scheduled_shocks:
        mag = shock.current_magnitude(state.t)
        if mag == 0:
            continue

        target = shock.target

        # 解析 target 路径: 'sector:energy.price'
        parts = target.split(':')
        if len(parts) == 2:
            obj_name, field = parts
            if obj_name.startswith('sector:'):
                sector = obj_name.split(':')[1]
                setattr(state.sector_state[sector], field,
                        getattr(state.sector_state[sector], field) * (1 + mag))
            else:
                setattr(getattr(state, obj_name), field,
                        getattr(getattr(state, obj_name), field) + mag)
```

---

## 8.4 危机内生涌现机制（Fire-Sale Externality）

⚠️ **单点 CAR 阈值不够——必须定义"被迫卖出的量"和"价格影响函数"。**

### 8.4.1 银行被迫卖出量

```python
def forced_sale_quantity(bank: CommercialBank, asset_type: str) -> dict:
    """
    银行 i 必须卖出的资产量
    核心: 资本缺口与流动性缺口的函数
    """
    # ─── 资本缺口 (CAR 触发) ───
    capital_gap = max(0, REQUIRED_CAR - bank.car) * bank.rwa

    # ─── 流动性缺口 (LCR 触发) ───
    liquidity_gap = max(0, REQUIRED_LCR - bank.lcr) * bank.expected_outflows

    # ─── 总缺口 ───
    total_gap = capital_gap + liquidity_gap

    if total_gap > 0:
        # 默认 60% 通过卖资产, 40% 通过缩贷款
        asset_sale = total_gap * 0.6
        loan_reduction = total_gap * 0.4
    else:
        asset_sale = 0
        loan_reduction = 0

    return {
        'asset_sale_amount': asset_sale,
        'loan_reduction': loan_reduction,
        'asset_type': asset_type,  # 通常先卖最流动的
    }
```

### 8.4.2 Fire-Sale 价格冲击函数

```python
def fire_sale_price_impact(
    asset_type: str,
    quantity: float,
    market_state: 'MarketState'
) -> float:
    """
    资产被迫卖出时, 价格变化率
    来源: Cifuentes-Ferrucci-Shin (2005), Brunnermeier-Pedersen (2009)
    """
    # ─── 1. 资产的市场深度参数 ───
    DEPTH = {
        'cash':                 1e9,
        'gov_bonds':            1e8,    # 政府债深度大
        'stocks':               1e7,    # 股票中等
        'corporate_bonds':      1e6,    # 公司债较浅
        'housing':              1e5,    # 房产深度浅!
        'real_estate_commercial': 1e4,  # 商业地产最浅
    }

    # ─── 2. 流动性参数（越低 → 冲击越大）───
    LIQUIDITY = {
        'gov_bonds':             1.0,
        'stocks':                0.9,
        'corporate_bonds':       0.7,
        'housing':               0.4,
        'real_estate_commercial': 0.3,
    }

    # ─── 3. 卖出量 / 深度 = 冲击比例 ───
    depth = DEPTH[asset_type]
    impact_ratio = quantity / depth

    # ─── 4. 基础价格影响 ───
    base_impact = impact_ratio * (1 - LIQUIDITY[asset_type])

    # ─── 5. 传染乘数 ───
    recent_volatility = market_state.recent_volatility
    contagion_sensitivity = 1.5

    # ─── 6. 拥挤交易 ───
    crowding_multiplier = market_state.num_sellers_same_asset

    # ─── 7. 总价格冲击 ───
    total_impact = (
        base_impact
      * contagion_sensitivity
      * recent_volatility
      * crowding_multiplier
    )

    # 限制: 单次价格下跌不超过 10%
    max_impact = 0.10
    total_impact = min(total_impact, max_impact)

    return -total_impact  # 负值 = 价格下跌
```

### 8.4.3 完整危机涌现路径

```
═══════════════════════════════════════════════════════
阶段 1: 信贷扩张期 (慢, 数年)
─────────────────────────────────────────────────────
  • 资产价格上涨 → 抵押品升值
  • 银行 CAR 上升 → 放贷标准放松
  • 内生信用扩张 → 更多资产需求 → 价格上涨
  • 银行杠杆率上升（Brock-Hommes 让价格偏离基本面）

阶段 2: 庞氏融资累积 (中速, 数月)
─────────────────────────────────────────────────────
  • 杠杆率超过历史 80 分位
  • 部分企业/家庭借新还旧 (interest_coverage < 1)
  • 脆弱性指标累积:
    - 银行平均 CAR 下降
    - 家庭 DTI 中位数上升
    - 信贷/GDP 缺口偏离 (BIS 指标)
  • 但 CAR 仍 > 阈值, 未触发甩卖

阶段 3: 明斯基时刻 (突发, 数日-数周)
─────────────────────────────────────────────────────
  触发条件 (任一):
    • 某银行 CAR < 4% (强制甩卖)
    • 资产价格单月跌幅 > 10% (触发保证金追缴)
    • 某大型 interbank 违约 (Cifuentes 触发)

  触发后:
    1. fire_sale_price_impact() 计算资产价格下跌
    2. 其他持有该资产银行的资本缩水
    3. → 多家银行 CAR 同时跌破阈值 (传染)
    4. → 多家银行同时甩卖 (拥挤交易)
    5. → 资产价格进一步下跌 (反馈环)
    6. → 银行间拆借冻结 (interbank 利率飙升)

  关键数学:
    • 单家 CAR < 阈值 → 卖 1%
    • 但因为传染: 5 家同时卖 → 总冲击 10%+
    • 因为拥挤: 价格影响非线性

阶段 4: 债务-通缩螺旋 (中速, 1-3 年)
─────────────────────────────────────────────────────
  • 资产价格下跌 → 抵押品价值下降
  • → 银行收紧信贷 (loan_reduction 路径)
  • → 企业投资收缩
  • → GDP 下降
  • → 价格水平下降 (deflation)
  • → 实际债务负担上升 (Fisher 效应)
  • → 企业违约增加 → 银行 NPL 上升
  • → 银行进一步收紧信贷
  • 闭环反馈, 直到某种稳态

阶段 5: 政策反应 (外生/内生)
─────────────────────────────────────────────────────
  • CB 降低政策利率 (零下限)
  • CB 启动 LOLR (最后贷款人)
  • 政府启动财政刺激
  • 政策有效性受当时约束限制
═══════════════════════════════════════════════════════
```

### 8.4.4 关键设计原则

1. **甩卖不是单点事件**——是传染性过程，多家银行同时或相继发生
2. **价格影响函数必须是数学的**，不是"触发→崩盘"的剧本规则
3. **不同资产有不同的流动性参数**——房产流动性远低于股票
4. **传染和拥挤放大**——非线性，不能用线性近似
5. **SFC 校验保证**：甩卖时，买方资金来自其他部门（不是凭空产生）

---

## 8.5 性能预算

⚠️ **100K 家庭 + 日级循环 = 计算瓶颈。必须在架构层面分层。**

### 8.5.1 性能目标

| 操作 | 预算 | 说明 |
|---|---|---|
| 月主 tick（10K agents） | ≤ 500 ms | 实时交互所需 |
| 月主 tick（100K agents） | ≤ 2000 ms | 异步场景 |
| 日级资产 sub-tick（参与家庭） | ≤ 50 ms | 30 个 sub-tick = 1.5s/月 |
| 单次 SFC 校验 | ≤ 20 ms | 月末聚合时 |
| 完整快照（Parquet 写入） | ≤ 100 ms | 每 12 月一次 |
| 状态读取（下钻 UI） | ≤ 50 ms | 用户触发 |

### 8.5.2 Agent 分层架构

```
┌────────────────────────────────────────────────────────┐
│              Agent 分层                                 │
├────────────────────────────────────────────────────────┤
│  Layer A: Full Behavior (10K–20K)                       │
│    • 完整状态 + 完整决策函数                              │
│    • 参与所有市场（消费、劳动、资产、信贷）                │
│    • 用于产生核心宏观现象                                │
│                                                         │
│  Layer B: Behavioral Bucket (100K+)  ❓ Phase 2         │
│    • 状态按桶聚合（财富分位 × 年龄段 × 部门）            │
│    • 决策用桶内均值 + 小幅扰动                           │
│    • 用于产生帕累托尾、统计代表性                        │
│    • 每月重新采样 5% 进入 Layer A（流动）               │
│    • ⚠️ 需验证不破坏尾部涌现                            │
│                                                         │
│  Layer C: Statistical Tail (无上限)  ❓ Phase 3         │
│    • top 1% 财富、top 0.1% 收入作为显式统计对象          │
│    • 不需要逐个 agent                                   │
│    • 满足"帕累托尾涌现"的实证要求                       │
└────────────────────────────────────────────────────────┘
```

> **MVP 策略**：只实现 Layer A（10K 家庭，全个体）。性能瓶颈通过以下方式解决：
> 1. Polars 列式存储 + 向量化操作
> 2. Numba JIT 编译热点函数
> 3. 资产市场参与资格过滤（见 8.5.3）
>
> Layer B/C 作为 Phase 2 的性能扩展，需要先验证不破坏帕累托尾涌现。

### 8.5.3 资产市场参与资格过滤

```python
def participates_in_daily_asset_market(hh: Household) -> bool:
    """
    只有"有交易意图的"家庭才进入日级循环
    默认: 总家庭数的 10%-20%
    """
    return (
        hh.stocks > 1000.0           # 持股 > 阈值
        or hh.housing_investment > 0   # 持有投资房
        or hh.job_search_intensity > 0.3  # 活跃求职者
    )
```

### 8.5.4 数据结构选型

| 数据 | 结构 | 理由 |
|---|---|---|
| Household 状态 | Polars DataFrame | 列式存储，向量化 |
| Firm 状态 | Polars DataFrame | 同上 |
| 银行状态 | dataclass 列表 | 数量小，不需要 DataFrame |
| 信贷网络 | SciPy.sparse CSR | 稀疏矩阵 |
| 时序数据 | Parquet 列存 | 压缩 + 列读 |
| 查询/分析 | DuckDB | SQL 接口 |

---

## 8.6 性能监控 🆕

```python
import time
from collections import defaultdict


class PerfMonitor:
    """仿真各阶段耗时监控"""

    def __init__(self):
        self.timings: dict[str, list[float]] = defaultdict(list)

    def measure(self, name: str) -> '_Timer':
        return self._Timer(self.timings, name)

    class _Timer:
        """上下文计时器"""
        def __init__(self, timings: dict, name: str):
            self.timings = timings
            self.name = name
            self._start: float | None = None

        def __enter__(self):
            self._start = time.perf_counter()
            return self

        def __exit__(self, *args):
            elapsed = time.perf_counter() - self._start
            self.timings[self.name].append(elapsed)

    def summary(self) -> str:
        """生成各阶段耗时分布报告"""
        lines = [f"{'Phase':<30} {'Mean (ms)':>10} {'P95 (ms)':>10} {'Calls':>8}"]
        lines.append("-" * 62)
        for name, times in sorted(self.timings.items()):
            if not times:
                continue
            import numpy as np
            mean_ms = np.mean(times) * 1000
            p95_ms = np.percentile(times, 95) * 1000
            lines.append(f"{name:<30} {mean_ms:>10.1f} {p95_ms:>10.1f} {len(times):>8}")
        return "\n".join(lines)


# 使用
perf = PerfMonitor()
with perf.measure('monthly_tick'):
    for day in range(30):
        with perf.measure('daily_asset_step'):
            asset_market.step()

# 每年末报告
if t % 12 == 0:
    logger.info(perf.summary())
```

**v0.1 → v0.2 修正**：
- ❌ 旧版 `_Timer.__init__` 缺少 `name` 参数 → ✅ 显式接收并存储
- ❌ 旧版 `__enter__` 缺少 `return self` → ✅ 修正
- 🆕 新增 `summary()` 方法生成格式化报告

---

## 8.7 可复现性

⚠️ **教学场景的核心要求——"同样的按钮 = 同样的结果"。**

### 8.7.1 RNG 流管理

```python
class RNGManager:
    """
    每个子系统有独立的 RNG 流
    好处: 调整一个模块的行为不影响其他模块的随机性
    """

    SUBSYSTEMS = [
        'household_init',
        'firm_init',
        'bank_init',
        'shock_injection',     # 政策/外生冲击
        'asset_price_noise',   # 日级资产市场噪音
        'labor_matching',      # 工作匹配
        'credit_allocation',   # 信贷分配
        'firm_pricing',        # 调价扰动
    ]

    def __init__(self, master_seed: int):
        self.seeds: dict[str, int] = {}
        base_rng = np.random.default_rng(master_seed)
        for sub in self.SUBSYSTEMS:
            self.seeds[sub] = int(base_rng.integers(0, 2**32))

    def stream(self, subsystem: str) -> np.random.Generator:
        """获取子系统的独立 RNG 流"""
        return np.random.default_rng(self.seeds[subsystem])

    def fork(self, new_master_seed: int) -> 'RNGManager':
        """从某个 tick 分叉，创建新随机序列"""
        return RNGManager(new_master_seed)

    def get_state(self) -> dict[str, int]:
        """获取当前所有子系统种子（用于快照恢复）"""
        return dict(self.seeds)

    def set_state(self, seeds: dict[str, int]):
        """恢复子系统种子（从快照）"""
        self.seeds = dict(seeds)
```

### 8.7.2 状态快照与恢复（Parquet）

```python
class StateSnapshot:
    """每个 tick 可保存完整状态到 Parquet，支持从任意 tick 恢复 + 重放"""

    def save(self, state: 'SimulationState', path: str):
        os.makedirs(path, exist_ok=True)
        state.households_df.to_parquet(f"{path}/households.parquet")
        state.firms_df.to_parquet(f"{path}/firms.parquet")
        state.banks_df.to_parquet(f"{path}/banks.parquet")
        state.macro_ts.to_parquet(f"{path}/macro_ts.parquet")

        metadata = {
            'tick': state.t,
            'master_seed': state.master_seed,
            'rng_seeds': state.rng_mgr.get_state(),
            'macro_snapshot': state.macro_ts.tail(1).to_dict('records')[0],
        }
        with open(f"{path}/metadata.json", 'w') as f:
            json.dump(metadata, f, indent=2, default=str)

    @classmethod
    def load(cls, path: str) -> 'SimulationState':
        """从 Parquet 恢复"""
        state = SimulationState()
        state.households_df = pl.read_parquet(f"{path}/households.parquet")
        state.firms_df = pl.read_parquet(f"{path}/firms.parquet")
        state.banks_df = pl.read_parquet(f"{path}/banks.parquet")
        state.macro_ts = pl.read_parquet(f"{path}/macro_ts.parquet")
        with open(f"{path}/metadata.json") as f:
            metadata = json.load(f)
        state.t = metadata['tick']
        state.master_seed = metadata['master_seed']
        state.rng_mgr.set_state(metadata['rng_seeds'])
        return state
```

### 8.7.3 重放与分叉（教学 UX 必备）

```python
class ReplayManager:
    """
    支持:
    1. 完整重放: 从 tick 0 重现
    2. 分叉: 从 tick T 改变某个决策，产生新分支
    """

    def replay(self, snapshot_path: str, end_tick: int) -> 'SimulationState':
        """从快照重放到 end_tick"""
        state = StateSnapshot.load(snapshot_path)
        while state.t < end_tick:
            state.step()
        return state

    def fork(self, snapshot_path: str, change_fn: Callable) -> 'SimulationState':
        """
        从快照分叉: 加载状态，应用 change_fn 修改，继续运行
        例: "假设 2008 年 9 月 CB 降息 1%"
        """
        state = StateSnapshot.load(snapshot_path)
        change_fn(state)  # 用户干预
        return state


# 教学 UX 使用
def user_intervention(state):
    """学生按下'降息'按钮"""
    state.cb.policy_rate -= 0.01  # 1%


forked = replay_mgr.fork('snapshots/t_240.parquet', user_intervention)
# forked 沿着"如果央行降息"的平行宇宙运行
```

### 8.7.4 场景快照库

```python
SCENARIO_SNAPSHOTS = {
    '2008_crisis_peak':     'snapshots/t_240.parquet',
    'pre_dot_com_bubble':   'snapshots/t_120.parquet',
    'post_war_boom':        'snapshots/t_030.parquet',
    'japanese_lost_decade': 'snapshots/t_600.parquet',
}
# 学生可以从任一历史时刻开始"如果..."
```

---

## 8.8 网络结构

### 8.8.1 网络层分类

| 层 | 内容 | 拓扑 | 涌现 | 阶段 |
|---|---|---|---|---|
| 1. Interbank | 银行间同业拆借 | Core-Periphery | 系统性风险传染 | Phase 2 |
| 2. Bank-Firm Credit | 银行对企业贷款 | 自适应 | 信贷紧缩传导 | Phase 1 (简化) |
| 3. Bank-HH Credit | 银行对家庭贷款 | 自适应 | 房贷危机 | Phase 1 (简化) |
| 4. Supply Chain | 企业间供应链 | 分层树 + 交叉 | 供给冲击 | Phase 3 |
| 5. Asset Cross-holding | 企业间交叉持股 | Scale-Free | 甩卖螺旋 | Phase 3 |
| 6. Labor | 行业就业分配 | 随机二部图 | 失业传染（弱） | Phase 1 |

### 8.8.2 各层拓扑

#### Interbank: Core-Periphery（Phase 2）

```
核心节点（5-10 家大银行）：互相紧密连接
外围节点（50-200 家小银行）：仅与 1-2 家核心相连

生成算法：
  1. 随机选 k 个核心
  2. 核心之间随机连边（密度 0.6）
  3. 每个外围节点连到 1-2 个核心
```

#### 供应链: 分层树 + 交叉（Phase 3）

```
Tier 1：原材料 → 资本品
Tier 2：资本品 → 消费品 / 高科技
Tier 3：消费品 / 高科技 → 最终需求
交叉：同层企业 10% 概率相互连接
```

#### 自适应信贷网络

```python
def update_credit_network(banks, firms, state):
    """
    自适应信贷网络生成
    🆕 优化: 关系贷款 + 粗筛, 避免每 tick 全量 O(N²)
    """
    changed = []
    dropped = []

    for firm in firms:
        # ─── 优化 1: 关系贷款 ───
        # 优先评估现有关系银行, 只在风险过高或不足时重新搜索
        current_banks = firm.relationship_banks
        needs_research = (
            len(current_banks) < 2  # 关系银行不足
            or any(risk_score(b, firm) > RISK_EXIT for b in current_banks)
        )

        if needs_research:
            # ─── 优化 2: 粗筛 ───
            # 按行业和规模过滤候选银行, 减少评估量
            candidates = [b for b in banks
                          if b.sector_exposure[firm.sector] < MAX_SECTOR_CONCENTRATION
                          and b.car > MIN_CAR_FOR_LENDING]

            # 只对候选做详细评分
            scores = {b: lending_score(b, firm, state) for b in candidates}
            top_k = sorted(scores, key=scores.get, reverse=True)[:3]
            changed.append((firm.id, [b.id for b in top_k]))

        # 切断高风险关系
        for b in current_banks:
            if risk_score(b, firm) > RISK_EXIT:
                dropped.append((firm.id, b.id))

    return changed, dropped


def lending_score(bank, firm, state) -> float:
    """银行对企业的综合评估"""
    return (
        0.3 * firm.cashflow_stability
      + 0.3 * (firm.collateral / max(firm.debt, 1))
      + 0.2 * (1 - min(firm.leverage, 5) / 5)   # 归一化
      + 0.1 * firm.credit_history
      + 0.1 * (1 - bank.npl_ratio)
    )
```

### 8.8.3 信贷网络涌现现象

| 现象 | 机制 |
|---|---|
| 信贷突然紧缩 | 银行危机 → 风险评估急升 → 切断关系 |
| 银行逃离风险 | 评估函数对违约概率极度敏感 |
| 信贷关系重组 | 危机后小客户被抛弃，迁移到大银行 |
| 关系贷款 vs 市场贷款 | 银行偏好熟悉的长期客户 |