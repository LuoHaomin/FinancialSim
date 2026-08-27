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

    # ── Monetary policy (Taylor Rule) ──
    cb_policy_rate_initial: float = 0.025
    cb_neutral_rate: float = 0.02
    taylor_inflation_coeff: float = 1.5   # π_π
    taylor_output_coeff: float = 0.5      # π_y
    taylor_smoothing: float = 0.85        # 利率平滑 (惯性 Taylor)
    taylor_rate_floor: float = -0.005     # 零利率下限

    # ── Fiscal (Phase 1: 完整预算) ──
    gov_spending_monthly: float = 0.0        # 固定政府购买; 0 = 自动按占潜在产出比例
    gov_spending_share_gdp: float = 0.45     # 自动模式: G = share × 潜在产出
                                             # 稳态校准: (1 − avg_mpc×(1−τ)) ≈ 0.475
    gov_unemployment_benefit: float = 0.5    # 失业救济 per unemployed HH / 月
    income_tax_rate: float = Field(default=0.25, ge=0.0, lt=1.0)
    corp_tax_rate: float = Field(default=0.21, ge=0.0, lt=1.0)
    fiscal_enabled: bool = True

    # ── Banking (利率传导 + 资本监管) ──
    deposit_rate_margin: float = -0.02    # 存款利率 = policy_rate + margin
    loan_rate_base_spread: float = 0.03   # 贷款基础利差
    loan_rate_car_pressure: float = 0.5   # CAR 每低于缓冲 1pt → 利差 +
    car_requirement: float = 0.08         # 资本充足率要求
    car_buffer: float = 0.02              # 缓冲 (低于 requirement+buffer 加价)

    # ── Firm (投资/折旧/定价) ──
    depreciation_rate: float = 0.01           # δ, 月度
    investment_sensitivity: float = 0.5       # 产出缺口→投资的敏感系数
    calvo_price_prob: float = 0.0             # 卡尔沃调价概率 (0=用库存规则;
                                              # 场景开启时注意加成棘轮会推高通胀)
    calvo_markup_target: float = 0.10         # 目标成本加成

    # ── Household (消费行为) ──
    wealth_effect_coef: float = 0.0          # λ: 超额财富拉动消费
                                             # 默认关闭: 纯存款型财富会直接转化为
                                             # 商品需求推高通胀; 引入资产市场后开启
    unemployment_replacement_rate: float = 0.4  # 救济替代率上限参考

    # ── Heterogeneity (初始化分布) ──
    hh_savings_rate_mean: float = 0.3
    hh_savings_rate_std: float = 0.1
    hh_mpc_mean: float = 0.7
    hh_mpc_std: float = 0.1
    hh_wage_lognormal_sigma: float = 0.3
    hh_initial_deposit_median: float = 20.0

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
