"""Firm agent (Phase 0 simplified).

Phase 0 仅包含:
- 单一部门, 简单线性生产
- 无资本折旧, 无 Calvo 定价, 无托宾 Q 投资

Phase 1 将扩展:
- CES 生产函数
- 卡尔沃定价
- 托宾 Q 投资 + 信贷约束
- 多部门 firms
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Firm:
    """Phase 0 简化企业 agent.

    字段 (按 phase 0 需求):
    - id, sector: 标识
    - capital, productivity: 生产参数
    - employees: 工人数
    - cash, deposits, debt: 财务
    - inventory, price, wage_offered: 运营
    """

    id: str
    sector: str

    # ── 生产 ──
    capital: float = 100.0
    productivity: float = 1.0
    employees: int = 0

    # ── 财务 ──
    cash: float = 0.0
    deposits: float = 0.0
    debt: float = 0.0

    # ── 运营 ──
    inventory: float = 0.0
    price: float = 10.0
    wage_offered: float = 1000.0

    # ── 决策方法 ──

    def production(self) -> float:
        """Phase 0: 线性生产 Y = productivity × employees."""
        return self.productivity * self.employees

    def revenue(self) -> float:
        return self.production() * self.price

    def labor_cost(self) -> float:
        return self.employees * self.wage_offered

    def profit(self) -> float:
        return self.revenue() - self.labor_cost()

    def sell(self, quantity: float) -> float:
        """卖出 quantity 件商品, 收入存入 deposits. 返回 revenue."""
        if quantity <= 0:
            return 0.0
        revenue = quantity * self.price
        self.deposits += revenue
        return revenue

    # ── 雇佣管理 ──

    def hire(self, n: int) -> None:
        """雇佣 n 人. 不超过预算约束 (Phase 1 加)."""
        if n > 0:
            self.employees += n

    def fire(self, n: int) -> None:
        """解雇 n 人. 不能降到 0 以下."""
        self.employees = max(0, self.employees - n)
