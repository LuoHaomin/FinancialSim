"""ProjectionLayer: state → 只读视图 (Polars 聚合 → JSON).

⚠️ 本模块是唯一允许读取 agent 状态的 UI 层代码; 输出全部为
不可变数据 (dict/list/标量), 不暴露任何 agent 对象引用.
"""
from __future__ import annotations

from financial_sim.core.state import SimulationState

# L1 宏观看板默认曲线 (键 = MacroSnapshot 字段 + 派生历史)
MACRO_KEYS = (
    "real_gdp", "inflation_yoy", "unemployment_rate",
    "policy_rate", "housing_price",
)
# series() 暴露的完整时序键 (MacroSnapshot 字段)
SERIES_KEYS = (
    "real_gdp", "nominal_gdp", "inflation_yoy", "unemployment_rate",
    "policy_rate", "avg_wage", "total_consumption", "total_output",
)


def macro_frame(state: SimulationState) -> dict:
    """单 tick 的 WS 帧 macro 部分 (与 SERIES_KEYS 对齐 + 房价).

    Args:
        state: 当前 SimulationState 快照.

    Returns:
        dict: 9 个标量键 (real_gdp/nominal_gdp/inflation_yoy/
        unemployment_rate/policy_rate/avg_wage/total_consumption/
        total_output/housing_price), 全部四舍五入到 6 位小数.
        央行缺失时 policy_rate 默认为 0.0.
    """
    return {
        "real_gdp": round(state.real_gdp, 6),
        "nominal_gdp": round(state.nominal_gdp, 6),
        "inflation_yoy": round(state.inflation_yoy, 6),
        "unemployment_rate": round(state.unemployment_rate, 6),
        "policy_rate": round(
            state.central_bank.policy_rate if state.central_bank else 0.0, 6
        ),
        "avg_wage": round(state.avg_wage(), 6),
        "total_consumption": round(state.total_consumption(), 6),
        "total_output": round(state.total_output(), 6),
        "housing_price": round(state.housing_price, 6),
    }


def series(state: SimulationState, from_t: int = 0,
           to_t: int | None = None) -> dict:
    """macro_history 投影为列式时序 (列对齐, 长度一致).

    MacroSnapshot 全字段 + 派生历史 (housing_price / price_level,
    按 tick 逐一对齐; 未覆盖的 tick 填 None).

    Args:
        state: 当前 SimulationState 快照.
        from_t: 起始 tick (含), 默认 0.
        to_t: 结束 tick (含), None 表示到最新.

    Returns:
        dict: 列式时序, 键 = 't' + SERIES_KEYS + ('housing_price',
        'price_level'); 每列长度一致; 派生列缺数据时填 None.
    """
    rows = [
        m for m in state.macro_history
        if m.t >= from_t and (to_t is None or m.t <= to_t)
    ]
    out: dict[str, list] = {"t": [m.t for m in rows]}
    for key in SERIES_KEYS:
        out[key] = [round(float(getattr(m, key)), 6) for m in rows]
    # 派生历史: 与 macro_history 在同一 tick 内逐条追加 → 按位置一一对应.
    # from_t/to_t 过滤后行号可能偏移, 用 (hist 长度 - macro 长度) 校正起点.
    n_macro = len(state.macro_history)
    for name, hist in (("housing_price", state.housing_price_history),
                       ("price_level", state.price_level_history)):
        col: list[float | None] = [None] * len(rows)
        offset = n_macro - len(hist)   # hist 落后 macro 的条数 (通常 0)
        if offset >= 0:
            for i, r in enumerate(rows):
                j = _position_of(state.macro_history, r.t) - offset
                if 0 <= j < len(hist):
                    col[i] = round(float(hist[j]), 6)
        out[name] = col
    return out


def _position_of(history: list, t: int) -> int:
    """macro_history 中 t 的位置 (history 按 t 递增, 每 tick 一条).

    Args:
        history: MacroSnapshot 列表 (按 t 单调递增).
        t: 目标 tick.

    Returns:
        int: 列表索引; 空列表返回 -1.
    """
    if not history:
        return -1
    return t - history[0].t


def firms_table(state: SimulationState) -> list[dict]:
    """L2 企业列表投影.

    Args:
        state: 当前 SimulationState 快照.

    Returns:
        list[dict]: 每元素 8 个键 (id/sector/employees/price/
        deposits/debt/last_sales/is_bankrupt); 金额字段四舍五入
        到 4 位小数.
    """
    return [
        {
            "id": f.id,
            "sector": f.sector,
            "employees": f.employees,
            "price": round(f.price, 4),
            "deposits": round(f.deposits, 4),
            "debt": round(f.debt, 4),
            "last_sales": round(f.last_sales, 4),
            "is_bankrupt": f.is_bankrupt,
        }
        for f in state.firms
    ]


def banks_table(state: SimulationState) -> list[dict]:
    """L2 银行列表投影.

    Args:
        state: 当前 SimulationState 快照.

    Returns:
        list[dict]: 每元素 7 个键 (id/capital/car/reserves/
        loans_to_firms/loans_to_households/is_failed). 资产为 0
        的银行 car 字段为 None; 其余 car 四舍五入到 6 位,
        金额字段到 4 位.
    """
    return [
        {
            "id": b.id,
            "capital": round(b.capital, 4),
            "car": round(b.car(), 6) if b.total_assets() > 0 else None,
            "reserves": round(b.reserves, 4),
            "loans_to_firms": round(b.loans_to_firms, 4),
            "loans_to_households": round(b.loans_to_households, 4),
            "is_failed": b.is_failed,
        }
        for b in state.banks
    ]


def agent_detail(state: SimulationState, sector: str,
                 agent_id: str) -> dict | None:
    """L3 单主体资产负债表投影 (MVP: firms/banks).

    Args:
        state: 当前 SimulationState 快照.
        sector: 部门标识, 支持 'firms' / 'banks'; 其他值返回 None.
        agent_id: 主体 id (firm.id 或 bank.id).

    Returns:
        dict | None: 资产负债表字典 (含 assets / liabilities /
        net_worth 或 capital / 运营/合规字段), 找不到主体时返回 None.
    """
    if sector == "firms":
        f = next((x for x in state.firms if x.id == agent_id), None)
        if f is None:
            return None
        return {
            "sector": sector,
            "id": f.id,
            "assets": {
                "deposits": round(f.deposits, 4),
                "inventory": round(f.inventory, 4),
                "capital_stock": round(f.capital, 4),
            },
            "liabilities": {
                "bank_loans": round(f.debt, 4),
            },
            "net_worth": round(
                f.deposits + f.inventory + f.capital - f.debt, 4
            ),
            "operational": {
                "employees": f.employees,
                "price": round(f.price, 4),
                "production": round(f.production(), 4),
                "is_bankrupt": f.is_bankrupt,
            },
        }
    if sector == "banks":
        b = next((x for x in state.banks if x.id == agent_id), None)
        if b is None:
            return None
        assets = {
            "reserves": round(b.reserves, 4),
            "loans_to_firms": round(b.loans_to_firms, 4),
            "loans_to_households": round(b.loans_to_households, 4),
            "gov_bonds_held": round(b.gov_bonds_held, 4),
            "reo_value": round(b.reo_value, 4),
            "seized_assets": round(b.seized_assets, 4),
            "repo_claims": round(b.repo_claims, 4),
        }
        liabilities = {
            "deposits_from_hh": round(b.deposits_from_hh, 4),
            "deposits_from_firms": round(b.deposits_from_firms, 4),
            "deposits_from_nbfi": round(b.deposits_from_nbfi, 4),
            "interbank_debt": round(b.interbank_debt, 4),
        }
        return {
            "sector": sector,
            "id": b.id,
            "assets": assets,
            "liabilities": liabilities,
            "capital": round(b.capital, 4),
            "car": round(b.car(), 6) if b.total_assets() > 0 else None,
            "is_failed": b.is_failed,
        }
    return None


def shock_log_view(state: SimulationState, limit: int = 200) -> list[dict]:
    """最近 N 条冲击日志 (倒序截断, 保留原顺序).

    Args:
        state: 当前 SimulationState 快照.
        limit: 最多返回条数, 默认 200.

    Returns:
        list[dict]: 截取的 shock_log 末尾切片 (引用的是原 dict,
        仅视图, 不复制内容).
    """
    return list(state.shock_log[-limit:])


# ════════════════════════════════════════════════════════════════
# A2: 部门资产负债表矩阵 (Godley 存量-流量视图)
# ════════════════════════════════════════════════════════════════

_ASSET_KEYS = {
    "cash", "deposits", "stocks", "bonds", "housing_self",
    "housing_investment", "consumer_durables", "inventories",
    "capital_stock", "interfirm_claims", "reserves", "loans_to_firms",
    "loans_to_households", "gov_bonds_held", "interbank_claims",
    "reo_value", "seized_assets", "repo_claims", "treasury_deposits",
    "other_assets", "gov_bonds", "lolr_claims",
}
_LIABILITY_KEYS = {
    "mortgage", "consumer_loan", "other_debt", "bank_loans",
    "bonds_issued", "accounts_payable", "minority_equity",
    "deposits_from_hh", "deposits_from_firms", "deposits_from_nbfi",
    "interbank_debt", "bonds_outstanding", "currency_issued",
    "fund_nav_liability", "repo_debt",
}

SECTOR_LABELS = {
    "households": "家庭", "firms": "企业", "banks": "银行",
    "government": "政府", "cb": "央行", "investment_bank": "投行",
    "asset_manager": "资管",
}


def sectors_matrix(state: SimulationState) -> dict:
    """7 部门资产负债表 → Godley 矩阵 (含 A = L + NW 校验标记).

    Args:
        state: 当前 SimulationState 快照.

    Returns:
        dict: 形如 {'t': int, 'sectors': {sector: {label, assets,
        liabilities, capital, total_assets, total_liabilities,
        net_worth, balanced}}}. zero-value 字段会被剔除;
        balanced = abs(TA - TL - NW) <= 1e-6 * max(1, |TA|).
    """
    bs = state.build_balance_sheets()
    sectors: dict[str, dict] = {}
    for name, sheet in bs.items():
        if sheet is None:
            continue
        assets, liabilities, capital = {}, {}, 0.0
        for k in _ASSET_KEYS:
            v = getattr(sheet, k, None)
            if isinstance(v, (int, float)) and v != 0.0:
                assets[k] = round(float(v), 4)
        for k in _LIABILITY_KEYS:
            v = getattr(sheet, k, None)
            if isinstance(v, (int, float)) and v != 0.0:
                liabilities[k] = round(float(v), 4)
        cap = getattr(sheet, "capital", None)
        if isinstance(cap, (int, float)):
            capital = round(float(cap), 4)
        ta = round(sheet.sum_assets(), 4)
        tl = round(sheet.sum_liabilities(), 4)
        nw = round(float(sheet.net_worth), 4)
        # A = L + NW 校验 (资本独立部门 NW 即 capital)
        balanced = abs(ta - tl - nw) <= 1e-6 * max(1.0, abs(ta))
        sectors[name] = {
            "label": SECTOR_LABELS.get(name, name),
            "assets": assets, "liabilities": liabilities,
            "capital": capital,
            "total_assets": ta, "total_liabilities": tl,
            "net_worth": nw, "balanced": balanced,
        }
    return {"t": state.t, "sectors": sectors}


# ════════════════════════════════════════════════════════════════
# A3: 家庭部门分布统计 (服务端聚合, 不暴露逐 agent 引用)
# ════════════════════════════════════════════════════════════════

def _gini(values: list[float]) -> float:
    """Gini 系数 (0=完全平等, 1=完全不平等).

    Args:
        values: 非负样本列表 (家庭财富或收入).

    Returns:
        float: 0.0 (空列表或非正总和) ~ 1.0 (极端集中);
        计算按排序累计法: (2*Σi*x_i)/(n*Σx) - (n+1)/n.
    """
    n = len(values)
    if n == 0:
        return 0.0
    xs = sorted(values)
    s = sum(xs)
    if s <= 0:
        return 0.0
    cum = 0.0
    for i, x in enumerate(xs, 1):
        cum += i * x
    return (2.0 * cum) / (n * s) - (n + 1.0) / n


def _quintile_means(values: list[float]) -> list[float]:
    """按排序五等分的组均值 (低→高).

    Args:
        values: 任意非空数值样本 (财富/收入).

    Returns:
        list[float]: 长度为 5 的列表, 第 i 个元素是排序后
        第 i 个五分位组的算术均值 (四舍五入到 4 位小数);
        空输入时返回 5 个 0.0.
    """
    n = len(values)
    if n == 0:
        return [0.0] * 5
    xs = sorted(values)
    return [
        round(sum(xs[i * n // 5:(i + 1) * n // 5]) / max(1, n // 5), 4)
        for i in range(5)
    ]


def households_stats(state: SimulationState) -> dict:
    """家庭部门聚合: 财富/收入分布、住房、就业、债务压力.

    Args:
        state: 当前 SimulationState 快照.

    Returns:
        dict: 含就业率、财富/收入 Gini、五等分组均值、Top10
        财富份额、自有住房率、按揭违约/水下比例、失业分布、
        财富直方图 (12 箱) 等; 部分字段在样本为 0 或总和
        为非正时返回 None.
    """
    price = getattr(state.stock_market, "price", 0.0) or 0.0
    hp = state.housing_price
    wealths, incomes = [], []
    owners = mortgagors = missed = underwater = unemployed = 0
    unemp_durations: list[int] = []
    wealth_hist_bins = 12
    for h in state.households:
        w = (h.cash + h.deposits + h.bonds + h.stock_units * price
             + h.housing_units * hp - h.mortgage_balance - h.consumer_loan)
        wealths.append(w)
        incomes.append(h.wage if h.employed else 0.0)
        if h.housing_units >= 1:
            owners += 1
        if h.mortgage_balance > 0:
            mortgagors += 1
            if h.mortgage_missed_payments > 0:
                missed += 1
            if h.months_underwater > 0:
                underwater += 1
        if not h.employed:
            unemployed += 1
            unemp_durations.append(h.unemployment_duration)
    n = len(state.households)
    xs = sorted(wealths)
    total_w = sum(xs)
    top10_share = (
        round(sum(xs[-max(1, n // 10):]) / total_w, 6) if total_w > 0 else None
    )
    # 财富直方图 (等宽分箱, min..max; 全零时退化为单箱)
    hist: list[int] = []
    if xs and xs[-1] > xs[0]:
        span = xs[-1] - xs[0]
        width = span / wealth_hist_bins
        hist = [0] * wealth_hist_bins
        for w in wealths:
            idx = min(wealth_hist_bins - 1, int((w - xs[0]) / width))
            hist[idx] += 1
    dur_hist: list[int] = []
    if unemp_durations:
        max_d = max(unemp_durations)
        if max_d > 0:
            bins = min(10, max_d)
            dur_hist = [0] * bins
            for d in unemp_durations:
                dur_hist[min(bins - 1, d * bins // max_d)] += 1
    return {
        "t": state.t,
        "n": n,
        "employment_rate": round((n - unemployed) / n, 6) if n else None,
        "gini_wealth": round(_gini(wealths), 6),
        "gini_income": round(_gini(incomes), 6),
        "wealth_quintiles": _quintile_means(wealths),
        "income_quintiles": _quintile_means(incomes),
        "top10_wealth_share": top10_share,
        "homeownership_rate": round(owners / n, 6) if n else None,
        "mortgagors": mortgagors,
        "mortgage_missed_share": (
            round(missed / mortgagors, 6) if mortgagors else None
        ),
        "negative_equity_share": (
            round(underwater / mortgagors, 6) if mortgagors else None
        ),
        "unemployed": unemployed,
        "avg_unemployment_duration": (
            round(sum(unemp_durations) / len(unemp_durations), 4)
            if unemp_durations else 0.0
        ),
        "wealth_histogram": {
            "bin_edges": _hist_edges(xs, wealth_hist_bins),
            "counts": hist,
        },
        "unemployment_duration_histogram": {"counts": dur_hist},
    }


def _hist_edges(xs_sorted: list[float], bins: int) -> list[float]:
    """等宽直方图箱边界 (含两端, 共 bins+1 个值).

    Args:
        xs_sorted: 已排序的样本.
        bins: 箱数.

    Returns:
        list[float]: 边界数组 (长度 bins+1); 输入退化时返回 [].
    """
    if not xs_sorted or xs_sorted[-1] <= xs_sorted[0]:
        return []
    lo, span = xs_sorted[0], xs_sorted[-1] - xs_sorted[0]
    return [round(lo + span * i / bins, 4) for i in range(bins + 1)]


# ════════════════════════════════════════════════════════════════
# A4: 政府 / 央行面板
# ════════════════════════════════════════════════════════════════

def government_view(state: SimulationState) -> dict | None:
    """政府面板: 资产负债 + 流量 + 财政参数.

    Args:
        state: 当前 SimulationState 快照.

    Returns:
        dict | None: 含 assets/liabilities/net_worth/flows/parameters
        五个子表; state.government 缺失时返回 None.
    """
    g = state.government
    if g is None:
        return None
    return {
        "t": state.t,
        "assets": {
            "treasury_deposits": round(g.treasury_deposits, 4),
            "other_assets": round(g.other_assets, 4),
        },
        "liabilities": {"bonds_outstanding": round(g.debt, 4)},
        "net_worth": round(g.treasury_deposits + g.other_assets - g.debt, 4),
        "flows": {
            "tax_revenue": round(g.tax_revenue, 4),
            "gov_spending": round(g.gov_spending, 4),
            "transfers": round(g.transfers, 4),
            "monthly_interest_paid": round(state.monthly_interest_paid, 4),
        },
        "parameters": {
            "income_tax_rate": round(g.income_tax_rate, 6),
            "corp_tax_rate": round(g.corp_tax_rate, 6),
            "bond_interest_rate": round(g.interest_rate, 6),
        },
    }


def central_bank_view(state: SimulationState) -> dict | None:
    """央行面板: 资产负债 + 政策参数 + 货币基数.

    Args:
        state: 当前 SimulationState 快照.

    Returns:
        dict | None: 含 assets/liabilities/capital/policy/
        monetary_base; LOLR 敞口聚合自 state.banks;
        state.central_bank 缺失时返回 None.
    """
    cb = state.central_bank
    if cb is None:
        return None
    return {
        "t": state.t,
        "assets": {
            "gov_bonds": round(cb.gov_bonds, 4),
            "lolr_claims": round(
                sum(b.lolr_debt for b in state.banks), 4
            ),
        },
        "liabilities": {
            "bank_reserves": round(cb.bank_reserves, 4),
            "currency_issued": round(cb.currency_issued, 4),
            "treasury_deposits": round(cb.treasury_deposits, 4),
        },
        "capital": round(cb.capital, 4),
        "policy": {
            "policy_rate": round(cb.policy_rate, 6),
            "target_inflation": round(cb.target_inflation, 6),
            "neutral_rate": round(cb.neutral_rate, 6),
            "output_gap": round(state.output_gap, 6),
        },
        "monetary_base": round(
            cb.currency_issued + cb.bank_reserves, 4
        ),
    }


# ════════════════════════════════════════════════════════════════
# A5: 网络图投影 (同业敞口 / 交叉持股)
# ════════════════════════════════════════════════════════════════

def network_view(state: SimulationState, kind: str) -> dict | None:
    """邻接结构 → 节点/边列表 (权重 = 敞口规模).

    Args:
        state: 当前 SimulationState 快照.
        kind: 'interbank' (同业敞口, 双向合并) 或
            'cross_holdings' (交叉持股, 按市值计权).

    Returns:
        dict | None: {'t', 'kind', 'nodes', 'edges'}, 边按 value
        降序; kind 不识别时返回 None.
    """
    if kind == "interbank":
        net = state.interbank_network
        nodes = [
            {
                "id": b.id,
                "capital": round(b.capital, 4),
                "car": round(b.car(), 6) if b.total_assets() > 0 else None,
                "failed": b.is_failed,
                "core": net is not None and b.id in net.core_ids,
            }
            for b in state.banks
        ]
        edges: list[dict] = []
        if net is not None:
            # 对称敞口 (a,b)+(b,a) 合并为无向边; 单向保留方向
            merged: dict[frozenset, dict] = {}
            for (a, b_id), amt in net.exposures.items():
                key = frozenset((a, b_id))
                if key in merged:
                    merged[key]["value"] += amt
                    merged[key]["bidirectional"] = True
                else:
                    merged[key] = {
                        "source": a, "target": b_id,
                        "value": round(amt, 4), "bidirectional": False,
                    }
            edges = sorted(
                merged.values(), key=lambda e: -e["value"]
            )
        return {"t": state.t, "kind": kind, "nodes": nodes, "edges": edges}
    if kind == "cross_holdings":
        ch = state.cross_holdings
        price = getattr(state.stock_market, "price", 0.0) or 0.0
        ids = set(ch.keys())
        for targets in ch.values():
            ids.update(targets.keys())
        deg: dict[str, float] = dict.fromkeys(ids, 0.0)
        edges = []
        for src, targets in ch.items():
            for dst, units in targets.items():
                v = round(units * price, 4)
                edges.append({"source": src, "target": dst, "value": v})
                deg[src] += v
                deg[dst] += v
        firm_ids = {f.id for f in state.firms}
        nodes = [
            {
                "id": i, "is_firm": i in firm_ids,
                "degree_value": round(deg[i], 4),
            }
            for i in sorted(ids)
        ]
        return {
            "t": state.t, "kind": kind, "nodes": nodes,
            "edges": sorted(edges, key=lambda e: -e["value"]),
        }
    return None


# ════════════════════════════════════════════════════════════════
# A6: 危机遥测 / 金融压力面板
# ════════════════════════════════════════════════════════════════

def stress_view(state: SimulationState) -> dict:
    """危机遥测面板: 抛压 / 银行 CAR / 住房 / 股市.

    Args:
        state: 当前 SimulationState 快照.

    Returns:
        dict: 含 fire_sale_pressure/housing_expectations_factor/
        failed_banks*/bankrupt_firms/bank_car (min/max/mean/
        below_requirement)/housing/stock_price; config.car_requirement
        缺失时 fallback 0.08.
    """
    housing = state.housing_market
    cars = [
        round(b.car(), 6) for b in state.banks if b.total_assets() > 0
    ]
    failed_now = sum(1 for b in state.banks if b.is_failed)
    bankrupt_firms = sum(1 for f in state.firms if f.is_bankrupt)
    return {
        "t": state.t,
        "fire_sale_pressure": round(state.fire_sale_pressure, 6),
        "housing_expectations_factor": round(
            state.housing_expectations_factor, 6
        ),
        "failed_banks": list(state.failed_banks),
        "failed_banks_now": failed_now,
        "bankrupt_firms": bankrupt_firms,
        "bank_car": {
            "min": min(cars) if cars else None,
            "max": max(cars) if cars else None,
            "mean": round(sum(cars) / len(cars), 6) if cars else None,
            "below_requirement": sum(
                1 for c in cars
                if c < float(getattr(state.config, "car_requirement", 0.08)
                             or 0.08)
            ),
        },
        "housing": {
            "price": round(state.housing_price, 6),
            "rent": round(housing.rent, 6) if housing else None,
            "rental_yield": (
                round(housing.rent * 12 / housing.price, 6)
                if housing and housing.price > 0 else None
            ),
            "sales_volume_month": (
                housing.sales_volume_month if housing else None
            ),
            "cumulative_default_units": (
                housing.cumulative_default_units if housing else None
            ),
        },
        "stock_price": round(
            float(getattr(state.stock_market, "price", 0.0) or 0.0), 6
        ),
    }


# ════════════════════════════════════════════════════════════════
# A8: SFC 违反详情 (逐 tick 文本)
# ════════════════════════════════════════════════════════════════

def sfc_view(state: SimulationState) -> dict:
    """逐 tick SFC 违反记录 (t 从 1 起, 与 sfc_violations 索引对应).

    Args:
        state: 当前 SimulationState 快照.

    Returns:
        dict: {'total_count': 累计违反条数, 'detail': 后 200 个
        非空违反项, 每项 {'t': tick, 'errors': [str, ...]}}.
    """
    detail = [
        {"t": i + 1, "errors": errs}
        for i, errs in enumerate(state.sfc_violations)
        if errs
    ]
    return {"total_count": sum(len(v) for v in state.sfc_violations),
            "detail": detail[-200:]}
