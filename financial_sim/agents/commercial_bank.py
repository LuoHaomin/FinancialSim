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
    """商业银行 agent (Phase 2: 多家 + 抵押贷款 + 同业)."""

    id: str = "bank_1"
    tier: int = 1                        # 1=核心, 2=外围 (Phase 2 网络结构)

    # ── 资产 ──
    reserves: float = 0.0
    loans_to_firms: float = 0.0
    loans_to_households: float = 0.0      # 包括抵押贷款 (Phase 2)
    gov_bonds_held: float = 0.0
    interbank_claims: float = 0.0         # 同业拆出 (Phase 2)

    # ── 负债 ──
    deposits_from_hh: float = 0.0
    deposits_from_firms: float = 0.0
    interbank_debt: float = 0.0           # 同业拆入 (Phase 2)
    lolr_debt: float = 0.0                # 最后贷款人债务 (Phase 2)

    # ── 资本 ──
    capital: float = 0.0

    # ── Phase 1+: NPL 跟踪 ──
    npl_amount: float = 0.0              # 不良贷款余额
    npl_writes_off_cumulative: float = 0.0  # 累计核销 (用于报告)
    npl_mortgages: float = 0.0            # 抵押贷款不良 (Phase 2)

    # ── Phase 2: 状态标志 ──
    is_failed: bool = False
    months_since_failure: int = 0
    reo_properties: int = 0               # 银行持有 (止赎) 房产数量

    # ── 监管/定价参数 ──
    car_requirement: float = 0.08
    car_buffer: float = 0.02
    loan_rate_base_spread: float = 0.03
    loan_rate_car_pressure: float = 0.5
    deposit_rate_margin: float = -0.02
    mortgage_rate_spread: float = 0.02   # 抵押贷款利率相对政策利率的溢价 (Phase 2)

    # ── 计算方法 ──

    def total_assets(self) -> float:
        return (
            self.reserves
            + self.loans_to_firms
            + self.loans_to_households
            + self.gov_bonds_held
            + self.interbank_claims
        )

    def total_liabilities(self) -> float:
        return (
            self.deposits_from_hh
            + self.deposits_from_firms
            + self.interbank_debt
            + self.lolr_debt
        )

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

    # ── Phase 2: 抵押贷款 NPL & 违约 ──

    def write_off_mortgage(self, amount: float) -> float:
        """核销抵押贷款: loans_to_households 减, capital 减, npl_mortgages 减.

        与 write_off_loan 类似, 但针对抵押贷款账户.
        """
        if amount <= 0:
            return 0.0
        actual = min(amount, self.npl_mortgages, self.loans_to_households)
        if actual <= 0:
            return 0.0
        self.loans_to_households -= actual
        self.npl_mortgages = max(0.0, self.npl_mortgages - actual)
        self.capital -= actual  # 损失直接侵蚀资本
        self.npl_writes_off_cumulative += actual
        return actual

    def is_under_capitalized(self, threshold: float) -> bool:
        """CAR 低于阈值 (Phase 2 失败门槛)."""
        return self.car() < threshold


__all__ = ["CommercialBank"]
