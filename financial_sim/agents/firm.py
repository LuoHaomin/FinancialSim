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
    home_bank_id: str | None = None  # Phase 3.5 PR-2: 贷款/存款所在银行 (多银行时随机分配)

    # ── 生产 ──
    capital: float = 100.0
    productivity: float = 1.0
    employees: int = 0
    capital_per_worker_target: float = 10.0  # 目标人均资本 (投资基准)

    # ── Phase 3 Week A: CES 生产函数 (production_function="ces" 时启用) ──
    production_function: str = "linear"   # "linear" | "ces"
    sigma_elasticity: float = 0.5         # 替代弹性 σ (ρ = 1 − 1/σ; σ=1 → Cobb-Douglas)
    alpha_capital: float = 0.3            # 资本份额 α (劳动份额 1−α)
    last_sales: float = 0.0               # 上月实际销售额 (定价/库存基准, step 层写入)
    last_demand: float = 0.0              # 上月总需求意向 (含库存不足未成交部分)
    sales_history: list[float] | None = None  # 销售额历史 (Week B 劳动需求基准)

    # ── Phase 3 Week C: 股权 ──
    shares_outstanding: int = 0            # IPO 后发行股数 (0 = 未上市)
    shares_held_by_firms: float = 0.0      # 已发行到企业股东名下的股数 (M3)
    dividend_received_from_firms: float = 0.0  # 当月作为股东收到的企业分红

    # ── Phase 3 Week E: 供应链 ──
    input_utilization: float = 1.0         # 当月中游投入满足率 ∈ [0,1]
    # IO 投入成本份额 (PR-7: 由 _supply_chain_cycle 按部门份额逐期写入).
    # 产出折减按份额加权: 缺 100% 投入 → 产出降 io_share (而非归零).
    # 原硬折减 (eff_a = A × util) 使 10% 的投入缺口瞬间清零全经济产出.
    io_input_share: float = 0.0
    demand_history: list[float] | None = None  # 需求意向历史 (Week B 劳动需求基准)

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

    # ── Phase 1+: 雇佣需求 + 违约追踪 ──
    baseline_employees: int = 0          # 目标就业(由 labor_market 在外部设定)
    months_negative_cashflow: int = 0    # 连续负现金流月数
    is_bankrupt: bool = False            # 破产标志
    months_bankrupt: int = 0             # 破产持续月数 (用于恢复判定)
    default_equity_threshold: float = 0.0  # 净资产 < 此值 → 违约
    bankruptcy_recovery: float = 0.5     # 资本清算回收率 (fire-sale 折扣)
    recovery_capital: float = 100.0      # 恢复时再注入的资本量

    def production(self) -> float:
        """产出.

        - linear: Y = A × L (Phase 0 形式)
        - ces:    Y = A × (α·K^ρ + (1−α)·L^ρ)^(1/ρ), ρ = 1 − 1/σ
          σ→∞ 时退化为线性; σ=1 时为 Cobb-Douglas A·K^α·L^(1−α) (数值守护).

        投入满足率的影响按成本份额加权 (PR-7):
          eff_util = 1 − io_share × (1 − util)
        io_share=0 (无 IO 约束) 时退化为原线性; io_share=α 与中间品
        成本份额一致 — 缺全部投入的产出损失 = 份额, 不是 100%.
        """
        util = getattr(self, "input_utilization", 1.0)
        io_share = min(1.0, max(0.0, getattr(self, "io_input_share", 0.0)))
        eff_util = 1.0 - io_share * (1.0 - util)
        if self.production_function != "ces":
            return self.productivity * eff_util * self.employees

        rho = 1.0 - 1.0 / self.sigma_elasticity
        labor = float(max(0, self.employees))
        if labor <= 0:
            return 0.0  # ρ<0 时劳动是必要投入 (互补情形), 无劳动即无产出
        if abs(rho) < 1e-6:
            # Cobb-Douglas 数值守护
            cap_term = self.capital ** self.alpha_capital
            lab_term = labor ** (1.0 - self.alpha_capital) if labor > 0 else 0.0
            return (
                self.productivity * eff_util
                * cap_term * lab_term
            )
        k_term = self.alpha_capital * self.capital ** rho
        l_term = (1.0 - self.alpha_capital) * labor ** rho
        eff_a = self.productivity * eff_util
        return eff_a * (k_term + l_term) ** (1.0 / rho)

    def revenue(self) -> float:
        """当期收入 = 产量 × 当前价格.

        Returns:
            float: production() (受生产函数 + 投入利用率影响) 乘以
                当前 self.price. 注意不扣除任何成本.
        """
        return self.production() * self.price

    def labor_cost(self) -> float:
        """当期工资总额 = 雇员数 × 工资率.

        Returns:
            float: 雇员数 × wage_offered. 简化: 无加班/工时区分, 不含
                社保/福利; 折旧与利息已分别通过 capital 与 debt 路径反映.
        """
        return self.employees * self.wage_offered

    def equity(self) -> float:
        """净资产 (资本化口径)."""
        return self.deposits + self.inventory + self.capital - self.debt

    def profit(self) -> float:
        """税前营业利润 = 收入 − 工资. 折旧/利息已通过资本/债务路径反映."""
        return self.revenue() - self.labor_cost()

    def is_default(self) -> bool:
        """Phase 1+ 违约判定: 净资产 < 阈值. 简化: 单一条件."""
        if self.is_bankrupt:
            return False  # 已处置
        return self.equity() < self.default_equity_threshold

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

    # ── Phase 1+: 破产处置 ──

    def declare_bankruptcy(self) -> dict[str, float]:
        """进入破产处置. 返回处置明细 dict:
            - recovered:  资本清算回收 (入 deposits)
            - debt_unpaid: 银行核销的贷款额
            - employees_fired: 解雇人数
        """
        if self.is_bankrupt:
            return {"recovered": 0.0, "debt_unpaid": 0.0, "employees_fired": 0}

        # 1. 资本清算: fire-sale 回收
        recovered = self.capital * self.bankruptcy_recovery
        self.capital = 0.0
        self.deposits += recovered

        # 2. 用存款尽可能偿还债务
        repayment = min(self.debt, self.deposits)
        self.deposits -= repayment
        unpaid_debt = self.debt - repayment
        self.debt = 0.0

        # 3. 解雇所有员工
        fired = self.employees
        self.employees = 0

        self.is_bankrupt = True
        self.months_bankrupt = 0

        return {
            "recovered": recovered,
            "debt_repaid": repayment,
            "debt_unpaid": unpaid_debt,
            "employees_fired": fired,
        }

    def tick_bankruptcy(self) -> None:
        """破产状态计时 (供 step 层每月调用)."""
        if self.is_bankrupt:
            self.months_bankrupt += 1

    def recapitalize(self, amount: float) -> None:
        """破产后重新注资: 资本注入 + 同额债务 (银行新贷款).

        SFC 注记: 这是资产端与负债端同步增加的"跨部门"操作, 调用方必须
        同时操作银行账目 (firm 存款/银行负债 + 银行对 firm 贷款).

        完整记账 (双方):
            firm.deposits += amount  (现金进入企业账户)
            firm.capital  += amount  (注入实物资本)
            firm.debt     += amount  (银行新贷款)
            bank.loans_to_firms    += amount
            bank.deposits_from_firms += amount
        """
        if amount <= 0:
            return
        self.deposits += amount
        self.capital = amount
        self.debt = amount      # 同额银行新贷款
        self.is_bankrupt = False
        self.months_bankrupt = 0
        # 不重置 employees — 由下个 tick 的 labor market 重新雇佣


__all__ = ["Firm"]
