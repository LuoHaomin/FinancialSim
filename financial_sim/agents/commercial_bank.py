"""CommercialBank agent.

Phase 1 行为:
- 利率定价: 存贷利差挂靠政策利率; 贷款溢价随资本充足率缺口顺周期上升
- 利润循环: 贷款利息收入 − 存款利息支出 → 留存进资本
- CAR 计算 (风险加权 Phase 2 加)

SFC 注记:
本类的资金操作只动银行自身账目; 借款人/存款人一侧的镜像记账
由 core/step.py 统一完成, 两边同步更新以满足跨部门一致性校验:
- 收贷款利息: capital += i 且借款人存款 −i (或债务资本化)
- 付存款利息: capital −= d 且存款人存款 += d
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CommercialBank:
    """商业银行 agent (Phase 1: 单一聚合银行)."""

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

    # ── Phase 1+: NPL 跟踪 ──
    npl_amount: float = 0.0              # 不良贷款余额
    npl_writes_off_cumulative: float = 0.0  # 累计核销 (用于报告)

    # ── 监管/定价参数 ──
    car_requirement: float = 0.08
    car_buffer: float = 0.02
    loan_rate_base_spread: float = 0.03
    loan_rate_car_pressure: float = 0.5
    deposit_rate_margin: float = -0.02

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
        """资本充足率 = capital / total_assets (简化: 未做风险加权)."""
        ta = self.total_assets()
        if ta == 0:
            return float("inf")
        return self.capital / ta

    def net_worth(self) -> float:
        """银行 NW = capital 字段. 不变量由 SFC 校验守护."""
        return self.capital

    def car_gap(self) -> float:
        """CAR 相对监管要求的缺口 (>0 = 不达标幅度)."""
        return max(0.0, (self.car_requirement + self.car_buffer) - self.car())

    # ── Phase 1: 利率定价 ──

    def set_rates(self, policy_rate: float, rate_floor: float = -0.005) -> tuple[float, float]:
        """根据政策利率设定存贷利率. 返回 (loan_rate, deposit_rate).

        - deposit_rate = max(下限, policy + margin)
        - loan_rate    = policy + base_spread + pressure × CAR 缺口
        """
        deposit_rate = max(rate_floor, policy_rate + self.deposit_rate_margin)
        spread = self.loan_rate_base_spread + self.loan_rate_car_pressure * self.car_gap()
        loan_rate = policy_rate + spread
        return loan_rate, deposit_rate

    # ── Phase 1: 利润循环 ──

    def book_loan_interest_income(self, amount: float) -> None:
        """确认贷款利息收入 → 资本. (借款人一侧由 step 层镜像.)"""
        if amount > 0:
            self.capital += amount

    def book_deposit_interest_expense(self, amount: float) -> None:
        """支付存款利息 → 资本减少. (存款人一侧由 step 层镜像加到存款.)"""
        if amount > 0:
            self.capital -= amount

    # ── Phase 1+: NPL & 违约处置 ──

    def npl_ratio(self) -> float:
        """不良贷款率 = npl / loans. 无贷款时返回 0."""
        total_loans = self.loans_to_firms + self.loans_to_households
        if total_loans <= 0:
            return 0.0
        return self.npl_amount / total_loans

    def mark_npl(self, amount: float) -> None:
        """标记不良 (仅记账, 不减资本)."""
        if amount > 0:
            self.npl_amount = max(0.0, self.npl_amount + amount)

    def write_off_loan(self, amount: float) -> float:
        """核销贷款: loans 减, capital 减 (同时减 npl).

        SFC 注记: A = L + capital 同步收缩, 保持不变量.
        返回实际核销金额 (≤ amount).
        """
        if amount <= 0:
            return 0.0
        # 受限于现有 NPL 余额
        actual = min(amount, self.npl_amount, self.loans_to_firms)
        if actual <= 0:
            return 0.0
        self.loans_to_firms -= actual
        self.npl_amount = max(0.0, self.npl_amount - actual)
        self.capital -= actual  # 损失直接侵蚀资本
        self.npl_writes_off_cumulative += actual
        return actual


__all__ = ["CommercialBank"]
