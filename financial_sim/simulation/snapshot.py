"""StateSnapshot: 状态快照保存/恢复.

Phase 1 最简实现: 仿真状态序列化为 JSON (可读 + 可 diff).
Parquet 列式快照 (大 N 家庭) Phase 2 加.

用法:
    StateSnapshot.save(sim, "snap.json")
    sim2 = StateSnapshot.load("snap.json")
"""
from __future__ import annotations

import json
from dataclasses import asdict, fields
from pathlib import Path

from financial_sim.agents.central_bank import CentralBank
from financial_sim.agents.commercial_bank import CommercialBank
from financial_sim.agents.firm import Firm
from financial_sim.agents.government import Government
from financial_sim.agents.household import Household
from financial_sim.config import SimConfig
from financial_sim.core.simulation import Simulation
from financial_sim.core.state import MacroSnapshot
from financial_sim.expectations.inflation import InflationExpectation
from financial_sim.markets.housing import HousingMarket


class SnapshotError(Exception):
    """快照版本不匹配或损坏."""


SNAPSHOT_VERSION = 3  # v3: 多企业 (firms 列表) — Phase 3 Week A

_AGENT_TYPES = {
    "household": Household,
    "firm": Firm,
    "bank": CommercialBank,
    "government": Government,
    "cb": CentralBank,
    "expectation": InflationExpectation,
    "macro": MacroSnapshot,
}


def _to_dict(obj: object) -> dict:
    """dataclass → 可 JSON 化的 dict, 带 type 标签."""
    d = asdict(obj)  # type: ignore[arg-type]
    return {"_type": type(obj).__name__, **d}


def _from_dict(d: dict, cls: type) -> object:
    valid = {f.name for f in fields(cls)}
    kwargs = {k: v for k, v in d.items() if k in valid}
    return cls(**kwargs)


class StateSnapshot:
    """保存/恢复完整仿真状态 (含 config + seed)."""

    @classmethod
    def save(cls, sim: Simulation, path: str | Path) -> Path:
        state = sim.state
        payload = {
            "_version": SNAPSHOT_VERSION,
            "seed": sim.seed,
            "t": state.t,
            "config": sim.config.model_dump(),
            "households": [_to_dict(h) for h in state.households],
            # v3: firms 列表 (state.firm 只是 firms[0] 的别名, 不单独存)
            "firms": [_to_dict(f) for f in state.firms],
            "bank": _to_dict(state.bank) if state.bank else None,
            "banks": [_to_dict(b) for b in state.banks],  # Phase 2: multi-bank
            "housing_market": (
                _to_dict(state.housing_market)
                if getattr(state, "housing_market", None) else None
            ),
            "government": _to_dict(state.government) if state.government else None,
            "cb": _to_dict(state.central_bank) if state.central_bank else None,
            "inflation_expectation": (
                _to_dict(state.inflation_expectation)
            ),
            "macro_history": [_to_dict(m) for m in state.macro_history],
            "price_level": state.price_level,
            "price_level_history": state.price_level_history,
            "real_gdp": state.real_gdp,
            "nominal_gdp": state.nominal_gdp,
            "inflation_yoy": state.inflation_yoy,
            "unemployment_rate": state.unemployment_rate,
            "potential_gdp": state.potential_gdp,
            "output_gap": state.output_gap,
            "housing_price": state.housing_price,
            "housing_price_history": state.housing_price_history,
            "housing_expectations_factor": state.housing_expectations_factor,
            "fire_sale_pressure": state.fire_sale_pressure,
            "failed_banks": state.failed_banks,
        }
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        return path

    @classmethod
    def load(cls, path: str | Path) -> Simulation:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        version = payload.get("_version")
        if version != SNAPSHOT_VERSION:
            msg = f"Snapshot version mismatch: {version} != {SNAPSHOT_VERSION}"
            raise SnapshotError(msg)

        sim = Simulation(config=SimConfig(**payload["config"]), seed=payload["seed"])
        state = sim.state

        state.households = [
            _from_dict(h, Household) for h in payload["households"]  # type: ignore[arg-type]
        ]
        if payload.get("firms"):
            state.firms = [
                _from_dict(f, Firm) for f in payload["firms"]  # type: ignore[arg-type]
            ]
        # Phase 2: 还原 multi-bank 列表
        if "banks" in payload and payload["banks"]:
            state.banks = [
                _from_dict(b, CommercialBank)  # type: ignore[arg-type]
                for b in payload["banks"]
            ]
        # 别名一致性: n_banks=1 时 state.bank 与 state.banks[0] 必须同一实例,
        # 否则不同代码路径写不同引用 → SFC 恒等式破裂.
        if len(state.banks) == 1 and payload["bank"]:
            state.bank = state.banks[0]
        elif payload["bank"]:
            state.bank = _from_dict(  # type: ignore[arg-type]
                payload["bank"], CommercialBank
            )
        # ── Phase 2: 住房市场 ──
        if payload.get("housing_market"):
            state.housing_market = _from_dict(  # type: ignore[arg-type]
                payload["housing_market"], HousingMarket
            )
        if payload["government"]:
            state.government = _from_dict(  # type: ignore[arg-type]
                payload["government"], Government
            )
        if payload["cb"]:
            state.central_bank = _from_dict(  # type: ignore[arg-type]
                payload["cb"], CentralBank
            )
        state.inflation_expectation = _from_dict(  # type: ignore[arg-type]
            payload["inflation_expectation"], InflationExpectation
        )
        state.macro_history = [
            _from_dict(m, MacroSnapshot) for m in payload["macro_history"]  # type: ignore[arg-type]
        ]

        # ── 宏观变量 ──
        state.t = payload["t"]
        state.price_level = payload["price_level"]
        state.price_level_history = payload["price_level_history"]
        state.real_gdp = payload["real_gdp"]
        state.nominal_gdp = payload["nominal_gdp"]
        state.inflation_yoy = payload["inflation_yoy"]
        state.unemployment_rate = payload["unemployment_rate"]
        state.potential_gdp = payload["potential_gdp"]
        state.output_gap = payload["output_gap"]
        # ── Phase 2: 住房 + fire-sale 状态 ──
        if "housing_price" in payload:
            state.housing_price = payload["housing_price"]
        if "housing_price_history" in payload:
            state.housing_price_history = payload["housing_price_history"]
        if "housing_expectations_factor" in payload:
            state.housing_expectations_factor = payload["housing_expectations_factor"]
        if "fire_sale_pressure" in payload:
            state.fire_sale_pressure = payload["fire_sale_pressure"]
        if "failed_banks" in payload:
            state.failed_banks = payload["failed_banks"]
        return sim
