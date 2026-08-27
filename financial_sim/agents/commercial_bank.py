"""CommercialBank agent (Phase 0 simplified).

Phase 0 仅包含:
- 单一聚合银行 (Phase 2 加入多家 + core-periphery 网络)
- 简单 CAR 计算 (Phase 1 加入 LCR/NSFR)
- 无利率传导 (Phase 1 加入完整传导链)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CommercialBank:
    """Phase 0 简化商业银行.

    字段对应 CommercialBankBalanceSheet 的简化版:
    - 资产: reserves, loans_to_firms, loans_to_households, gov_bonds_held
    - 负债: deposits_from_hh, deposits_from_firms
    - 资本: capital

    Phase 1 加入: loans_by_firm (按借款人拆分), NPL 比率,
                  risk_weighted_assets, LCR, NSFR
    """

    id: str = "bank_1"

    # ── 资产 ──
    reserves: float = 0.0
    loans_to_firms: float = 0.0
    loans_to_households: float = 0.0
    gov_bonds_held: float = 0.0

    # ── 负债 ──
    deposits_from_hh: float = 0.0
    deposits_from_firms: float = 0.0

    # ── 资本 ──
    capital: float = 0.0

    # ── 计算方法 ──

    def total_assets(self) -> float:
        return (
            self.reserves
            + self.loans_to_firms
            + self.loans_to_households
            + self.gov_bonds_held
        )

    def total_liabilities(self) -> float:
        return self.deposits_from_hh + self.deposits_from_firms

    def car(self) -> float:
        """资本充足率 = capital / total_assets.

        Phase 0 简化: 用总资产而非风险加权资产.
        """
        if self.total_assets() == 0:
            return float("inf")  # 没有资产时, CAR 无定义
        return self.capital / self.total_assets()

    def net_worth(self) -> float:
        """银行 NW = capital 字段 (独立追踪).

        不变量: total_assets() == total_liabilities() + capital.
        当违反时, SFC 校验会报错.
        """
        return self.capital
