"""Scenario loader: 把 scenarios/*.yaml 装配为 SimConfig + 触发偏移.

用法:
    from financial_sim.scenarios import load_scenario
    cfg = load_scenario("crisis_2008")  # 默认触发 t=12
    sim = Simulation(cfg, seed=cfg.seed)
    sim.run(cfg.n_ticks)

设计 (IMPLEMENTATION.md §5.0 P0-c):
- 每个 scenario 是一个 YAML 文件, 包含 SimConfig 字段 + 可选 trigger_offsets
- YAML 顶层 key 直接映射到 SimConfig 字段; 顶层字段 `trigger_offsets` 是
  列表, 与 preset_shocks 一一对应 (决定每个 shock 在哪个 tick 触发)
- 未指定的字段走 SimConfig 默认

错误处理:
- 文件不存在 → FileNotFoundError
- 字段名错误 → pydantic ValidationError
- trigger_offsets 长度不匹配 → ValueError
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from financial_sim.config import SimConfig
from financial_sim.simulation.events import build_event_manager

SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "scenarios"


def list_scenarios() -> list[str]:
    """列出 scenarios/ 目录下所有 YAML 文件名 (无扩展名)."""
    if not SCENARIOS_DIR.exists():
        return []
    return sorted(p.stem for p in SCENARIOS_DIR.glob("*.yaml"))


def load_scenario(
    name: str,
    overrides: dict[str, Any] | None = None,
) -> tuple[SimConfig, Any]:
    """加载指定 scenario, 返回 (SimConfig, EventManager|None).

    Parameters
    ----------
    name : str
        scenario 名 (不带 .yaml 后缀)
    overrides : dict, optional
        在 YAML 之上再覆盖一层 (用于测试 / 临时调参)

    Returns
    -------
    (SimConfig, EventManager | None)
        EventManager 仅在 scenario 含 preset_shocks 时非 None; trigger_offsets
        从 YAML 顶层读, 缺省则全部在 t=12 触发.

    Raises
    ------
    FileNotFoundError
        scenario 文件不存在
    ValueError
        trigger_offsets 长度与 preset_shocks 不匹配
    """
    path = SCENARIOS_DIR / f"{name}.yaml"
    if not path.exists():
        msg = (
            f"Scenario '{name}' not found at {path}. "
            f"Available: {list_scenarios()}"
        )
        raise FileNotFoundError(msg)

    with path.open("r", encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)

    # 取出 trigger_offsets, 剩余字段进 SimConfig
    trigger_offsets = data.pop("trigger_offsets", None)
    if overrides:
        data.update(overrides)

    cfg = SimConfig(**data)

    em = None
    if cfg.preset_shocks:
        em = build_event_manager(cfg.preset_shocks, trigger_offsets)
    return cfg, em


__all__ = ["SCENARIOS_DIR", "list_scenarios", "load_scenario"]
