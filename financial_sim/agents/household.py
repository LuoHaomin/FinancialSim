"""Household agent.

Phase 1 行为:
- 消费 = MPC × 永久收入 + 财富效应 (λ × 超额净财富), 受流动性约束
- 永久收入用收入的指数滑动平均近似
- 异质性: savings_rate / mpc / wage 从 config 分布抽样初始化
  (在 Simulation._build_state 中完成, 不是在本文件里抽样)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Household:
    """家庭 agent.

    字段:
    - id: 唯一标识
    - sector: 当前就职部门 (None = 失业)
    - wage: 月工资; employed 时有效
    - employed / unemployment_duration: 就业状态
    - cash: 现金 (须与 CB.currency_issued 对应)
    - deposits: 银行存款 (须与 bank.deposits_from_hh 对应)
    - income: 当期可支配收入 (税后)
    - permanent_income: 收入的指数滑动平均 (消费基准)
    - savings_rate / mpc: 异质行为参数
    - wealth_effect_coef λ: 每单位超额财富拉动的边际消费
    - housing_units: 自住/投资房数量 (Phase 2)
    - mortgage_balance: 房贷余额 (Phase 2)
    - rental_income: 当月收到的租金 (Phase 2)
    """

    id: str
    sector: str | None = None
    employer_id: str | None = None  # 雇主 firm.id (Phase 3 多企业)
    home_bank_id: str | None = None  # Phase 3.5 PR-2: 存款所在的银行 (多银行时随机分配)

    # ── 就业 ──
    wage: float = 0.0
    employed: bool = True
    unemployment_duration: int = 0

    # ── 金融 ──
    cash: float = 0.0
    deposits: float = 0.0
    income: float = 0.0

    # ── 行为参数 (Phase 0 同构 → Phase 1 异质初始化) ──
    savings_rate: float = 0.3
    mpc: float = 0.7

    # ── Phase 1: 永久收入 + 财富效应 ──
    permanent_income: float = 0.0
    income_adapt_speed: float = 0.2       # 永久收入更新的平滑系数
    wealth_effect_coef: float = 0.0       # 默认 0 → 与 Phase 0 完全一致
    wealth_buffer_months: float = 3.0     # 前 N 个月永久收入视为"缓冲", 不拉动消费

    # ── Phase 2: 住房 + 抵押贷款 ──
    housing_units: int = 0                 # 持有的住房数量 (自住 1 + 投资 N)
    mortgage_balance: float = 0.0          # 房贷余额
    mortgage_rate: float = 0.0             # 房贷利率 (锁定)
    rental_income: float = 0.0             # 当月租金收入
    mortgage_missed_payments: int = 0      # 连续错过月供次数 (断供压力计)
    months_underwater: int = 0             # 连续负资产月数 (Phase 3.5 行为化违约通道)

    # ── Phase 3 前置: 消费信贷 (P0-a) + 私人持债 (P0-b) ──
    consumer_loan: float = 0.0             # 消费贷余额
    consumer_loan_rate: float = 0.0        # 消费贷利率 (发放时锁定)
    credit_denied_months: int = 0           # 连续被信贷配给拒绝的月数 (教学诊断)
    bonds: float = 0.0                     # 持有国债面值

    # ── Phase 3 Week C/D: 股票 + 基金 ──
    stock_units: float = 0.0               # 自持股票指数单位数
    fund_units: float = 0.0                # 基金份额 (资产管理者代持, Week D)
    risk_tolerance: float = 0.5            # 风险偏好 ∈ [0,1] (组合选择)

    def decide_consumption(self) -> float:
        """消费决策: c = mpc·Y^perm + λ·max(0, NW − buffer·Y^perm).

        流动性约束 (c ≤ 存款) 在 step 层施加, 因为需要联动 SFC 记账.
        """
        pi = self.permanent_income if self.permanent_income > 0 else self.income
        target = self.mpc * pi
        excess_wealth = max(0.0, self.net_worth() - self.wealth_buffer_months * pi)
        target += self.wealth_effect_coef * excess_wealth
        return max(0.0, target)

    def decide_savings(self) -> float:
        """储蓄 = 收入 − 意愿消费 (下限 0)."""
        return max(0.0, self.income - self.decide_consumption())

    def update_permanent_income(self) -> None:
        """每个 tick 末更新永久收入: 指数滑动平均."""
        if self.permanent_income <= 0:
            self.permanent_income = self.income
            return
        a = min(1.0, max(0.0, self.income_adapt_speed))
        self.permanent_income += a * (self.income - self.permanent_income)

    def net_worth(self) -> float:
        """金融净资产 = 现金 + 存款 + 债券 − 房贷 − 消费贷.

        有意**不含住房**: 一方面避免对房价的循环依赖, 另一方面住房是非流动
        资产, 对消费的边际影响远小于流动财富 (房产财富效应由
        `housing_equity()` 单独提供给需要它的调用方).
        """
        return (
            self.cash + self.deposits + self.bonds
            - self.mortgage_balance - self.consumer_loan
        )

    def housing_equity(self, housing_price: float) -> float:
        """房屋净值 = 房价 × 数量 − 房贷余额."""
        return housing_price * self.housing_units - self.mortgage_balance

    def mortgage_payment(self) -> float:
        """月供 (本息). 假设 N=30 年期 (360 月)."""
        if self.mortgage_balance <= 0 or self.mortgage_rate <= 0:
            return 0.0
        r = self.mortgage_rate / 12.0
        n = 360
        # 标准等额本息: P × r / (1 - (1+r)^-n)
        return self.mortgage_balance * r / (1.0 - (1.0 + r) ** (-n))

    # ── 就业状态管理 ──

    def lose_job(self) -> None:
        """失业. 重置 unemployment_duration."""
        self.employed = False
        self.unemployment_duration = 0
        self.employer_id = None

    def find_job(
        self, sector: str, wage: float, employer_id: str | None = None,
    ) -> None:
        """找到工作. 重置失业计时, 切换部门."""
        self.employed = True
        self.unemployment_duration = 0
        self.sector = sector
        self.wage = wage
        self.employer_id = employer_id

    def tick_unemployment(self) -> None:
        """失业 +1 月. 仅在 unemployed 时调用."""
        if not self.employed:
            self.unemployment_duration += 1


__all__ = ["Household"]
