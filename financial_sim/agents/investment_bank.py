"""InvestmentBank: 自营指数持仓 + 回购杠杆 + VaR 风控 (Phase 3 Week D).

策略: 以资本为底仓, 借回购加杠杆持有指数; 波动率上升 → VaR 约束收紧
→ 目标杠杆下降 → 被动卖出 (顺周期去杠杆 / fire-sale 传导).

SFC 注记 (镜像由 step 层联动银行/市场完成):
- 回购 = 以持仓作质押向商业银行借入存款:
    ib.deposits ↑R ↔ bank.deposits_from_nbfi ↑R;  ib.repo_debt ↑R
- 平仓卖出 + 还款与折扣 (haircut) 由 step 双边记账.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class InvestmentBank:
    """投资银行 agent."""

    id: str = "ib_1"

    # ── 资产 ──
    deposits: float = 0.0
    stock_units: float = 0.0

    # ── 负债 ──
    repo_debt: float = 0.0

    # ── 资本 ──
    capital: float = 0.0

    # ── 状态 ──
    realized_vol: float = 0.10          # 滚动波动率估计 (VaR 输入)
    is_deleveraging: bool = False       # 触发强平 (教学诊断)
    return_history: list[float] | None = None

    # ── 参数 (from_config 注入) ──
    var_confidence_budget: float = 2.0  # VaR 预算: kσ 占资本上限比例分母
    leverage_max: float = 5.0           # 名义最大杠杆
    margin_requirement: float = 0.08    # capital/assets 下限, 跌破触发强平

    @classmethod
    def from_config(cls, config) -> InvestmentBank:
        """从配置对象构造 InvestmentBank 实例.

        读取三类风控参数 (其余字段在 simulation 启动后由 step 层写入):
            - ib_leverage_max: 名义最大杠杆 (默认 5.0)
            - ib_margin_requirement: capital/assets 下限 (默认 0.08)
            - ib_var_budget: VaR 预算 k (默认 2.0)

        Args:
            config: 全局配置对象, 需含 ``ib_leverage_max`` /
                ``ib_margin_requirement`` / ``ib_var_budget`` 三个可选字段
                (缺失则用默认值).

        Returns:
            InvestmentBank: 全新实例, 默认 id="ib_1".
        """
        return cls(
            id="ib_1",
            leverage_max=float(getattr(config, "ib_leverage_max", 5.0)),
            margin_requirement=float(getattr(config, "ib_margin_requirement", 0.08)),
            var_confidence_budget=float(getattr(config, "ib_var_budget", 2.0)),
        )

    def position_value(self, price: float) -> float:
        """持仓市值 = 持仓单位 × 当前价格.

        Args:
            price: float, 当前股票指数价格.

        Returns:
            float: 持仓端市值, 忽略现金存款端 (deposits 另计入 margin_call_gap).
        """
        return self.stock_units * price

    def leverage(self, price: float) -> float:
        """实际杠杆率 = 持仓市值 / 资本.

        资本 ≤ 1e-9 时视为 1e-9 以避免除零 (此时若持仓市值 > 0 则
        杠杆为极大值, 触发 margin_call_gap 报警).

        Args:
            price: float, 当前股票价格.

        Returns:
            float: 杠杆倍数. 与 ``target_leverage()`` 比较用于去杠杆决策.
        """
        cap = self.capital if self.capital > 1e-9 else 1e-9
        return self.position_value(price) / cap

    def update_vol(self, ret: float, decay: float = 0.20,
                   floor: float = 0.05) -> None:
        """EWMA 波动率更新 (月度收益 → 年化)."""
        self.realized_vol = max(
            floor,
            (1 - decay) * self.realized_vol + decay * abs(ret) * (12 ** 0.5),
        )

    def target_leverage(self) -> float:
        """VaR 约束下的目标杠杆: lev ≤ budget / σ.

        经典 A (Adrian-Shin) 机制: 波动↑ → 杠杆目标↓ (顺周期).
        """
        lev_var = self.var_confidence_budget / max(self.realized_vol, 1e-6)
        return min(self.leverage_max, lev_var)

    def desired_position(self, price: float) -> float:
        """目标持仓市值 = 目标杠杆 × 资本."""
        return self.target_leverage() * self.capital

    def margin_call_gap(self, price: float) -> float:
        """>0 表示资本充足率达标缺口 (需补足的金额)."""
        assets = self.deposits + self.position_value(price)
        req = self.margin_requirement * assets
        return max(0.0, req - self.capital)
