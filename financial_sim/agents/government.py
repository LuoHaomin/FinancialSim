"""Government agent (Phase 0 simplified).

Phase 0 仅包含:
- 简化预算约束: G + TR + INT = T + ΔB
- 基本税收 (income tax + corporate tax)

Phase 1 加入:
- 自动稳定器 (失业救济随失业率变化)
- 多级税率
- 国债持有结构 (银行 vs CB vs 家庭)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Government:
    """Phase 0 简化政府 agent.

    字段:
    - debt: 总国债存量
    - tax_revenue: 当期税收
    - gov_spending: 政府购买 G
    - transfers: 转移支付 TR
    - interest_rate: 国债平均利率
    - income_tax_rate: 所得税率 (默认 25%)
    - corp_tax_rate: 公司税率 (默认 21%)
    """

    # ── 债务 ──
    debt: float = 0.0

    # ── 流量 ──
    tax_revenue: float = 0.0
    gov_spending: float = 0.0  # Phase 0 关闭
    transfers: float = 0.0     # Phase 0 关闭

    # ── 参数 ──
    interest_rate: float = 0.025
    income_tax_rate: float = 0.0  # Phase 0 关闭
    corp_tax_rate: float = 0.0    # Phase 0 关闭

    # ── 决策方法 ──

    def collect_taxes(self, total_income: float, total_profit: float) -> float:
        """收取所得税 + 公司税. 返回税收总额."""
        income_tax = total_income * self.income_tax_rate
        corp_tax = max(0.0, total_profit) * self.corp_tax_rate
        self.tax_revenue = income_tax + corp_tax
        return self.tax_revenue

    def compute_interest(self) -> float:
        """国债利息 = debt × rate."""
        return self.debt * self.interest_rate

    def primary_balance(self) -> float:
        """初级余额 = 税收 - 非利息支出."""
        return self.tax_revenue - self.gov_spending - self.transfers

    def issue_debt_to_balance(
        self,
        gov_spending: float,
        transfers: float,
        tax_revenue: float,
        interest_payment: float,
    ) -> None:
        """按预算恒等式更新国债:
        ΔB = G + TR + INT - T

        赤字 → 增债; 盈余 → 减债.
        """
        deficit = gov_spending + transfers + interest_payment - tax_revenue
        self.debt += deficit
