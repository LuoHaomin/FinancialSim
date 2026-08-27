"""消费信贷市场 (Phase 3 前置批次 P0-a).

设计动机 (IMPLEMENTATION.md §5.0 P0-a):
- 资管/投行的对手方是负债家庭, 信贷配给逻辑会被企业融资复用
- 引入家庭部门主动负债渠道, 让消费信贷冲击 (信用紧缩) 涌现
- 为 Phase 3 Week D 的资管赎回螺旋做前置准备

简化范围:
- 申请机制: 每 tick 家庭按"流动性缺口"自动提出贷款申请
- 配给规则 (Stiglitz-Weiss 简化): 银行按 DTI (Debt-to-Income) 阈值筛选,
  拒绝高 DTI 申请 → 模拟"信贷配给"现象. 不建模信息不对称与利率逆向选择.
- 利率: 固定加点 (policy_rate + consumer_loan_spread), 单一利率档.
- 期限: 等额本息 60 月 (5 年), 与房贷的 360 月分离.

SFC 注记:
- 发放: hh.deposits ↑L / hh.consumer_loan ↑L
         bank.deposits_from_hh ↑L / bank.loans_to_households ↑L
         (钱凭空产生 → 内生信用创造, 不动准备金)
- 还款: 等额本息 → 利息 (bank.capital ↑) + 本金 (bank.loans_to_hh ↓)
         hh.deposits ↓payment / hh.consumer_loan ↓principal
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ConsumerCreditMarket:
    """消费信贷市场配置 (per-month 规则)."""

    dti_limit: float = 0.40              # DTI 上限: 余额 / 月可支配收入
    loan_term_months: int = 60           # 等额本息期数 (默认 5 年)
    income_multiple_cap: float = 3.0     # 单笔贷款额 / 月可支配收入上限
    min_income_to_borrow: float = 0.5    # 月可支配收入下限 (穷人不给贷)
    lending_fraction: float = 0.7        # 银行实际批准的比例 (简化配给)

    # ── 决策方法 ──

    def desired_loan(self, monthly_income: float, deposits: float) -> float:
        """家庭希望借入的金额 (基于流动性缺口).

        缺口 = (永久收入 - 现金存款) × MPC, 上限 income_multiple_cap × 月入,
        下限 0.
        """
        if monthly_income <= 0:
            return 0.0
        gap = max(0.0, monthly_income - deposits)
        return min(self.income_multiple_cap * monthly_income, gap)

    def is_eligible(self, monthly_income: float, deposits: float) -> bool:
        return monthly_income >= self.min_income_to_borrow

    def approves(self, monthly_income: float, current_balance: float,
                 requested: float) -> bool:
        """银行是否批准贷款: 配给规则 — 新 DTI 超阈值则拒绝.

        用 lending_fraction 概率批准 (隐含配给: 不是所有合格申请都批).
        """
        if monthly_income <= 0:
            return False
        new_balance = current_balance + requested
        new_dti = new_balance / monthly_income
        # 简化: 总是批准合格的 (lending_fraction 在上层做总规模调控)
        return new_dti <= self.dti_limit

    def monthly_payment(self, principal: float, annual_rate: float) -> float:
        """等额本息: P × r / (1 − (1+r)^−n), 其中 r = 年率/12."""
        if principal <= 0 or annual_rate <= 0:
            return 0.0
        r = annual_rate / 12.0
        n = self.loan_term_months
        return principal * r / (1.0 - (1.0 + r) ** (-n))


__all__ = ["ConsumerCreditMarket"]
