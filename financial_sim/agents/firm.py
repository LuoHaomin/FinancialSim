"""Firm agent.

Phase 1 行为:
- 生产 Y = productivity × employees (Phase 0 线性形式保留;
  CES 生产函数 Phase 2+ 引入)
- 资本折旧 K ← K(1−δ), 每月调用
- 投资决策: 加速器规则 I = sensitivity × max(0, desired_K − K)
- 定价: 库存缓冲规则 (Phase 0) 或卡尔沃概率调价 (calvo_price_prob > 0 时)

SFC 注记:
- 投资 = 存款 → 资本品的资产内部置换, 不改变部门总资产
- 借款补工资由 step 层完成 (联动银行记账)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Firm:
    """企业 agent."""

    id: str
    sector: str

    # ── 生产 ──
    capital: float = 100.0
    productivity: float = 1.0
    employees: int = 0
    capital_per_worker_target: float = 10.0  # 目标人均资本 (投资基准)

    # ── 财务 ──
    cash: float = 0.0
    deposits: float = 0.0
    debt: float = 0.0

    # ── 运营 ──
    inventory: float = 0.0
    price: float = 10.0
    wage_offered: float = 1000.0

    # ── 参数 ──
    depreciation_rate: float = 0.01      # δ 月度
    investment_sensitivity: float = 0.5
    calvo_price_prob: float = 0.0        # 0 = 用库存规则
    calvo_markup_target: float = 0.10

    def production(self) -> float:
        """线性生产 Y = productivity × employees."""
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

    # ── Phase 1: 资本/投资 ──

    def depreciate(self) -> None:
        """K ← K(1−δ). 仅减少资本存量, 不涉及资金流."""
        self.capital *= 1.0 - self.depreciation_rate

    def desired_capital(self) -> float:
        """目标资本 = 人均目标 × 雇员数."""
        return self.capital_per_worker_target * self.employees

    def decide_investment(self) -> float:
        """加速器投资: I = sensitivity × max(0, K* − K).

        再受融资约束约束 (不借新钱投资): 上限为可用存款.
        """
        gap = max(0.0, self.desired_capital() - self.capital)
        want = self.investment_sensitivity * gap
        return min(want, self.deposits)

    def invest(self, amount: float) -> None:
        """执行投资: capital ← capital + I.

        SFC 注记: 在单一聚合企业的设定下, 资本形成等价于留存利润的
        实物化 — 只增加企业部门资产存量, 不涉及跨部门资金流
        (因此不动 deposits). Phase 2 引入资本品部门后改为真实采购.
        decide_investment 已用可用存款做审慎上限.
        """
        actual = max(0.0, amount)
        self.capital += actual

    # ── Phase 1: 定价 ──

    def marginal_cost(self) -> float:
        """单位劳动成本 / 生产率 (单一投入的边际成本)."""
        if self.productivity <= 0:
            return self.price
        return self.wage_offered / self.productivity

    def maybe_calvo_reprice(self, draw_uniform_01: float) -> bool:
        """卡尔沃定价: 以 calvo_price_prob 概率把价格调到成本 × (1+加成).

        抽签由外部用 RNGManager 流完成, 保证可复现.
        返回是否调价.
        """
        if self.calvo_price_prob <= 0 or not (0.0 <= draw_uniform_01 < 1.0):
            return False
        if draw_uniform_01 < self.calvo_price_prob:
            self.price = self.marginal_cost() * (1 + self.calvo_markup_target)
            return True
        return False

    # ── 雇佣管理 ──

    def hire(self, n: int) -> None:
        """雇佣 n 人."""
        if n > 0:
            self.employees += n

    def fire(self, n: int) -> None:
        """解雇 n 人. 不能降到 0 以下."""
        self.employees = max(0, self.employees - n)


__all__ = ["Firm"]
