"""Configuration loader for FinancialSim.

Phase 0: minimal config support. Will be expanded in Phase 1.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class SimConfig(BaseModel):
    """Top-level simulation configuration."""

    name: str = "baseline"
    description: str = ""
    seed: int = 42

    # Time
    n_ticks: int = Field(default=1200, ge=1)
    days_per_month: int = Field(default=30, ge=1)

    # Population
    n_households: int = Field(default=1000, ge=1)
    n_firms_per_sector: int = Field(default=50, ge=1)
    sectors: list[str] = Field(default_factory=lambda: ["consumer_goods"])
    n_banks: int = Field(default=1, ge=1)

    # Initial conditions
    initial_gdp: float = 1000.0
    initial_inflation: float = 0.02
    nairu: float = 0.05
    target_inflation: float = 0.02

    # Policy
    cb_policy_rate_initial: float = 0.025
    cb_neutral_rate: float = 0.02

    # Other settings
    enable_housing: bool = False
    enable_brock_hommes: bool = False
    enable_events: bool = False

    @classmethod
    def from_yaml(cls, path: str | Path) -> SimConfig:
        """Load configuration from a YAML file."""
        path = Path(path)
        if not path.exists():
            msg = f"Config file not found: {path}"
            raise FileNotFoundError(msg)
        with path.open("r", encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f)
        return cls(**data)

    @classmethod
    def default(cls) -> SimConfig:
        """Return default configuration."""
        return cls()
