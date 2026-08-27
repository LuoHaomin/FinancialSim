"""Housing market (Phase 2).

设计 (MARKETS.md §4.5 + AGENTS.md §3.2.4):
- 房价锚定: P = annual_rent / rental_yield_target
- 月度调整: 偏离目标比率时, 房价向目标值回归 (调整速度 housing_price_adjust_speed)
- 抵押贷款市场 (Phase 2.1): 在银行 tick 内调用

SFC 注记: 房价变化不直接动账目; 抵押贷款的发放/偿还在 bank tick 完成.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HousingMarket:
    """Phase 2 住房市场: 房价 + 抵押贷款簿记.

    字段:
    - price: 当前每单位房价 (一单位 = 一套房)
    - rent: 月租金 (锚定 cap rate = annual_rent / price)
    - total_units: 经济体总住房存量 (固定)
    - sales_volume_month: 当月交易量 (供流动性度量)
    """

    price: float = 200.0
    rent: float = 10.0
    total_units: int = 1000
    sales_volume_month: int = 0
    cumulative_default_units: int = 0   # 累计因违约进入银行 REO 的住房

    # ── 配置 (由 from_config 设置) ──
    rental_yield_target: float = 0.05   # 年化 cap rate: rent × 12 / price
    adjust_speed: float = 0.10
    ltv_max: float = 0.80
    mortgage_rate_spread: float = 0.02
    default_ltv_threshold: float = 1.10

    @classmethod
    def from_config(cls, config) -> HousingMarket:
        return cls(
            price=getattr(config, "housing_initial_price", 200.0),
            rent=getattr(config, "housing_initial_rent", 10.0),
            rental_yield_target=getattr(config, "housing_rental_yield_target", 0.05),
            adjust_speed=getattr(config, "housing_price_adjust_speed", 0.10),
            ltv_max=getattr(config, "housing_ltv_max", 0.80),
            mortgage_rate_spread=getattr(config, "housing_mortgage_rate_spread", 0.02),
            default_ltv_threshold=getattr(config, "housing_default_ltv_threshold", 1.10),
        )

    @property
    def cap_rate(self) -> float:
        """年化 cap rate = 月租金 × 12 / 房价. 反映租金回报率."""
        if self.price <= 0:
            return 0.0
        return self.rent * 12.0 / self.price

    def revalue(self, policy_rate: float, expectations_factor: float = 1.0) -> None:
        """月度房价调整: 锚定 cap rate + 利率反馈.

        逻辑:
        1. 目标价格 = (rent × 12) / rental_yield_target
        2. 利率上调 → 目标 cap rate 上调 → 目标价格下调
           adjusted_cap = rental_yield_target + 0.5 × policy_rate
        3. 价格向目标调整: P_new = P_old + speed × (P_target − P_old)
        4. 期望因子: expectations_factor > 1 → 泡沫 (价格超过基本面)
        """
        # 利率反馈 (简化): cap rate 与政策利率正相关
        adjusted_cap = self.rental_yield_target + 0.5 * max(0.0, policy_rate)
        if adjusted_cap <= 0:
            return
        target_price = (self.rent * 12.0 / adjusted_cap) * expectations_factor
        self.price += self.adjust_speed * (target_price - self.price)
        self.price = max(self.price, 1.0)  # 防止跌到 0

    def max_mortgage(self, monthly_income: float) -> float:
        """LTV 约束下最大可贷额.

        Phase 2 简化: 仅考虑 LTV (price × ltv_max), 不考虑 DTI (Phase 3).
        假设首付 = price × (1 − ltv_max).
        """
        return self.price * self.ltv_max

    def is_underwater(self, housing_units: int, mortgage_balance: float) -> bool:
        """房贷余额 / 房价 = LTV. > threshold → 负资产 → 违约倾向."""
        house_value = housing_units * self.price
        if house_value <= 0:
            return mortgage_balance > 0
        return (mortgage_balance / house_value) > self.default_ltv_threshold

    def update_rent(self, inflation: float) -> None:
        """月租金跟随通胀指数化."""
        self.rent *= (1.0 + inflation / 12.0)
        self.rent = max(self.rent, 0.01)


__all__ = ["HousingMarket"]
