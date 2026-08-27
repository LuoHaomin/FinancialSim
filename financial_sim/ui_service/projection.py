"""ProjectionLayer: state → 只读视图 (Polars 聚合 → JSON).

⚠️ 本模块是唯一允许读取 agent 状态的 UI 层代码; 输出全部为
不可变数据 (dict/list/标量), 不暴露任何 agent 对象引用.
"""
from __future__ import annotations

from financial_sim.core.state import SimulationState

# L1 宏观看板默认曲线 (键 = MacroSnapshot 字段)
MACRO_KEYS = (
    "real_gdp", "inflation_yoy", "unemployment_rate",
    "policy_rate", "housing_price",
)


def macro_frame(state: SimulationState) -> dict:
    """单 tick 的 WS 帧 macro 部分."""
    return {
        "real_gdp": round(state.real_gdp, 6),
        "inflation_yoy": round(state.inflation_yoy, 6),
        "unemployment_rate": round(state.unemployment_rate, 6),
        "policy_rate": round(
            state.central_bank.policy_rate if state.central_bank else 0.0, 6
        ),
        "housing_price": round(state.housing_price, 6),
    }


def series(state: SimulationState, from_t: int = 0,
           to_t: int | None = None) -> dict:
    """macro_history 投影为列式时序 (列对齐, 长度一致)."""
    rows = [
        m for m in state.macro_history
        if m.t >= from_t and (to_t is None or m.t <= to_t)
    ]
    out: dict[str, list] = {"t": [m.t for m in rows]}
    for key in ("real_gdp", "inflation_yoy", "unemployment_rate",
                "policy_rate"):
        out[key] = [round(float(getattr(m, key)), 6) for m in rows]
    # 房价在 MacroSnapshot 中不存在; 由 state 房价历史尾巴补齐
    hp_hist = state.housing_price_history
    if rows:
        tail = hp_hist[len(hp_hist) - len(rows):] if hp_hist else []
        out["housing_price"] = [
            round(float(v), 6) for v in tail
        ] if len(tail) == len(rows) else [None] * len(rows)
    return out


def firms_table(state: SimulationState) -> list[dict]:
    """L2 企业列表投影."""
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
    """L2 银行列表投影."""
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
    """L3 单主体资产负债表投影 (MVP: firms/banks)."""
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
    return list(state.shock_log[-limit:])
