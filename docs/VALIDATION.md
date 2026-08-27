# 涌现目标与校准

> 返回：[DESIGN.md](../DESIGN.md)
> 版本：v0.2 | 2026-08-27

---

## 12.1 目标现象清单

| # | 现象 | 涌现自 | 验证标准 | 阶段 |
|---|---|---|---|---|
| 1 | 明斯基周期 | 内生信用 + 异质信念 + 银行失败规则 | 100 次跑中重现 >50 次 | Phase 2 |
| 2 | 金融加速器 | 日级资产价格 → 银行资本 → 信贷 | 房价跌 10%，投资下降 >2% | Phase 1 |
| 3 | 债务-通缩螺旋 | 价格粘性 + 实际债务负担 + 内生信用 | 通缩 + 实际 GDP 下降 | Phase 2 |
| 4 | 银行间挤兑 | Core-Periphery interbank + CAR 阈值 | 单家失败传染 N 家 | Phase 2 |
| 5 | 帕累托财富分布 | 个体家庭 + 异质储蓄率 + 资产复利 | top 1% 财富占比 >30% | Phase 1 |
| 6 | 中产空心化 | 工资 vs 资产价格增速差 | 中位数实际收入停滞 | Phase 2 |
| 7 | 能源冲击传导 | CES + 部门供应链 + 工资粘性 | 能源价格 50% 涨 → GDP 短期下降 | Phase 1 |
| 8 | 房价泡沫 | 抵押贷款 + 银行资本顺周期 | 房价/收入比峰值 >8 | Phase 2 |
| 9 | 政策误判 | 手动覆盖 + 反应滞后 | 央行滞后 → 通胀加剧 | Phase 1 |
| 10 | 部门轮动 | 资本跨部门 + TFP 异速 | 资本品占比相对消费品变化 | Phase 3 |
| 11 | 银行顺周期利润 🆕 | 利润→资本→放贷能力 | 丰年 NPL↓ CAR↑ 信贷↑ | Phase 2 |
| 12 | 违约级联 🆕 | 企业违约→银行NPL→信贷紧缩→更多违约 | 单个大型违约引发链式反应 | Phase 2 |

---

## 12.2 Stylized Facts 验证

通过"stylized facts test"——不需要精确数值，仅需定性重现：

| # | 事实 | 验证方法 |
|---|---|---|
| 1 | GDP 单位根 + 周期性波动 | ADF 检验：无法拒绝单位根；频谱分析：存在 5-10 年周期 |
| 2 | 产出与就业高度协动 | corr(ΔGDP, ΔEmployment) > 0.7 |
| 3 | 短期菲利普斯曲线 | 通胀变动与失业缺口负相关 |
| 4 | 财富分布服从帕累托尾 | top 1% 占比 25-45%；尾部指数 α ≈ 1.5-2 |
| 5 | 企业规模服从 Zipf 律 | log(firm_size) vs log(rank) 斜率 ≈ -1 |
| 6 | 金融变量厚尾性、波动聚集 | kurtosis > 3；|r_t| 自相关 > 0.1 |
| 7 | 危机事件内生涌现 | 无外生冲击下出现资产价格急跌 > 10% |

---

## 12.3 Calibration Suite（自动化测试）

⚠️ **验证不能靠人眼——必须用 pytest 风格的回归测试。**

### 12.3.1 测试套件

```python
# tests/calibration/test_stylized_facts.py

import pytest
import numpy as np
from financial_sim.core import Simulation


SCENARIOS = [
    'baseline',
    'tight_credit',
    'loose_credit',
    'energy_shock',
    'high_inflation',
]


@pytest.fixture(scope='session')
def monte_carlo_results(tmp_path_factory):
    """运行 N 次蒙特卡洛，保存结果"""
    n_runs = 50
    results = []
    for seed in range(n_runs):
        sim = Simulation(scenario='baseline', seed=seed, ticks=1200)
        results.append(sim.run())
    return results


# ─── 测试 1: 财富帕累托尾 🆕 修正 ───
@pytest.mark.parametrize('scenario', SCENARIOS)
def test_wealth_pareto_tail(scenario, monte_carlo_results):
    """top 1% 财富占比应在 25-45% 之间"""
    for r in monte_carlo_results:
        wealth = r.household_wealth  # Series: 每个家庭的财富
        total = wealth.sum()
        top1_threshold = wealth.quantile(0.99)
        top1_share = wealth[wealth >= top1_threshold].sum() / total
        assert 0.25 < top1_share < 0.45, \
            f"{scenario}: top 1% share = {top1_share:.3f}"


# ─── 测试 2: 危机涌现 ───
@pytest.mark.parametrize('seed', range(20))
def test_crisis_emergence_loose_credit(seed):
    """宽松信贷场景下，应涌现危机 (50%+)"""
    sim = Simulation(scenario='loose_credit', seed=seed, ticks=600)
    result = sim.run()
    crashes = result.detect_crashes(min_drop=0.10)
    assert len(crashes) > 0, f"seed={seed}: no crisis emerged"


# ─── 测试 3: 波动聚集 ───
def test_volatility_clustering(monte_carlo_results):
    """股价应表现出波动聚集 (GARCH 效应)"""
    for r in monte_carlo_results:
        returns = r.stock_index.pct_change().dropna()
        autocorr = returns.abs().autocorr(lag=1)
        assert autocorr > 0.1, f"volatility clustering weak: {autocorr:.3f}"


# ─── 测试 4: 厚尾 ───
def test_stock_returns_fat_tails(monte_carlo_results):
    """股价收益率应呈厚尾 (kurtosis > 3)"""
    for r in monte_carlo_results:
        returns = r.stock_index.pct_change().dropna()
        kurt = returns.kurtosis()
        assert kurt > 3, f"kurtosis too low: {kurt:.1f}"


# ─── 测试 5: 产出-就业协动 ───
def test_gdp_unemployment_corr(monte_carlo_results):
    """GDP 增长与就业增长应高度正相关"""
    for r in monte_carlo_results:
        gdp_growth = r.gdp.pct_change(12).dropna()
        emp_growth = r.employment.pct_change(12).dropna()
        corr = gdp_growth.corr(emp_growth)
        assert corr > 0.7, f"GDP-employment correlation: {corr:.2f}"


# ─── 测试 6: SFC 守恒 ───
@pytest.mark.parametrize('scenario', SCENARIOS)
def test_sfc_consistency(scenario):
    """所有 tick 必须通过 SFC 校验"""
    sim = Simulation(scenario=scenario, seed=0, ticks=1200)
    sim.run()
    assert len(sim.sfc_violations) == 0, \
        f"SFC violations: {len(sim.sfc_violations)}"


# ─── 测试 7: 银行顺周期利润 🆕 ───
def test_bank_pro_cyclicality():
    """经济上行期银行利润应上升"""
    sim = Simulation(scenario='baseline', seed=42, ticks=600)
    result = sim.run()
    # GDP 增长快的时期，银行利润率也应上升
    gdp_growth = result.gdp.pct_change(12)
    bank_roe = result.bank_profit / result.bank_capital
    corr = gdp_growth.corr(bank_roe)
    assert corr > 0.3, f"bank pro-cyclicality weak: {corr:.2f}"


# ─── 测试 8: 性能 ───
def test_performance_budget():
    """月主 tick 应 < 500ms (10K agents)"""
    sim = Simulation(scenario='baseline', seed=0, n_households=10_000, ticks=12)
    times = []
    for t in range(12):
        start = time.perf_counter()
        sim.step()
        times.append(time.perf_counter() - start)
    p95 = np.percentile(times, 95)
    assert p95 < 0.5, f"P95 tick time: {p95*1000:.0f}ms"
```

**v0.1 → v0.2 修正**：
- ❌ 旧版 `quantile(0.99)` 返回第 99 百分位数值（非占比）→ ✅ 先取阈值再筛选求和
- 🆕 新增测试 7（银行顺周期）

### 12.3.2 持续集成

```yaml
# .github/workflows/calibration.yml
name: Calibration
on:
  pull_request:
    paths: ['financial_sim/**', 'tests/calibration/**']
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -e '.[dev]'
      - run: pytest tests/calibration/ -v --tb=short
      - uses: actions/upload-artifact@v4
        with:
          name: calibration-report
          path: reports/
```

### 12.3.3 校准报告

```
╔══════════════════════════════════════════════════════════╗
║  CALIBRATION REPORT - baseline scenario                  ║
╠══════════════════════════════════════════════════════════╣
║  ✓ Pareto tail:        top 1% share = 32%              ║
║  ✓ Volatility cluster: autocorr = 0.18                 ║
║  ✓ Fat tails:          kurtosis = 6.2                  ║
║  ✓ GDP-emp corr:       0.84                            ║
║  ✓ SFC:                0 violations                     ║
║  ✓ Bank pro-cyc:       ROE-GDP corr = 0.45             ║
║  ✓ Performance:        P95 = 312ms                     ║
╚══════════════════════════════════════════════════════════╝
```

---

## 12.4 学术对比

每个版本应能重现以下经验结果：

| 现象 | 真实数据（参考） | 模型目标 | 容差 |
|---|---|---|---|
| 财富基尼系数 | 0.85 (US, SCF) | - | ±0.05 |
| 房价/收入比 | 5-10 (US) | - | ±2 |
| 失业率 SD/GDP SD | 4-5x (Okun) | - | ±1 |
| 银行 CAR 波动 | 8-15% (BIS) | - | ±2 |
| 通胀持久性 | 0.7-0.9 (GDP deflator) | - | ±0.1 |

---

## 13. 校准参数

### 13.1 参数来源

| 参数类型 | 来源 | 备注 |
|---|---|---|
| 经济周期参数 | 真实国家数据 | 美国/中国季度数据 |
| 部门 TFP 增长率 | KLEM 数据库 | 跨国平均 |
| 银行参数 | BIS 报告 | CAR/LCR 阈值 |
| 家庭行为 | 消费调查 | SCF / CHFS |
| 初始条件 | 起点 + 稳态 | 平衡路径 |

### 13.2 稳态初始化策略 🆕

> 教学模拟必须从一个合理的稳态出发，否则前 50 个月都在做无意义的过渡。

```python
def initialize_to_steady_state(config):
    """
    从校准的目标稳态出发，反向推算各部门初始存量
    """
    # 1. 设定宏观稳态目标
    gdp = config.target_gdp
    inflation = config.target_inflation  # 2%
    unemployment = config.nairu          # 5%

    # 2. 反向推算部门存量
    # 劳动: L = labor_force × (1 - unemployment)
    # 资本: K 由资本产出比推算
    for sector in config.sectors:
        sector.capital = sector.capital_output_ratio * sector.gdp_share * gdp
        sector.labor = sector.labor_share * labor_force * (1 - unemployment)

    # 3. 金融部门: 按监管要求初始化
    for bank in config.banks:
        bank.car = 0.10  # 初始高于监管要求
        bank.lcr = 1.20  # 初始高于监管要求

    # 4. 家庭: 按分布生成，但确保总量匹配
    # 净资产总和 = 资本存量 + 政府债券 - 企业债务 - 政府净债务

    # 5. Burn-in 期: 运行 100 个月让系统稳定
    sim = Simulation(state=initial_state, seed=config.seed)
    for _ in range(100):
        sim.step()

    # 6. 保存 burn-in 后的状态作为场景起点
    return sim.state
```

### 13.3 ❓ 校准决策待定

- 是否跟随中国数据 vs 美国数据？
- 初始年份：1950 / 1980 / 2000 / 2020？
- 简化的"风格化数值"是否够用？
- Burn-in 期长度：100 个月是否足够？