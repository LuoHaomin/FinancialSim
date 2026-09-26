"""AssetManager: 代理家庭持仓 + 申购赎回 (Phase 3 Week D).

机制: 家庭把部分股票持仓转入基金换份额 (过户, 无现金流); 净值 NAV =
(现金池+持仓市值)/份额. 表现差时赎回 → 被动抛售压价 → 更多赎回
(赎回螺旋, 由 step 层的市场价格联动驱动).

SFC 注记:
- 赎回 = 家庭赎回权 ↓ / AM 现金池↓或抛售变现 → 家庭存款 ↑;
- 无自有资本: A ≡ L (NAV 定义式), capital 恒 0.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AssetManager:
    """资产管理 agent."""

    id: str = "am_1"

    # ── 资产 ──
    deposits: float = 0.0               # 现金缓冲池
    stock_units: float = 0.0            # 代客持仓

    # ── 负债/份额 ──
    fund_units_outstanding: float = 0.0

    # ── 状态 ──
    nav_history: list[float] | None = None
    redemption_rate: float = 0.0        # 当月赎回率 (教学诊断)

    @classmethod
    def from_config(cls, config) -> AssetManager:
        """从配置对象构造 AssetManager 实例.

        当前只读取 id 字段 ("am_1"); 其余状态在 simulation 启动后由
        step 层依家庭申购/赎回流写入.

        Args:
            config: 全局配置对象 (实际未用字段, 保留以与同模块其他
                agent 的 ``from_config`` 接口一致).

        Returns:
            AssetManager: 全新实例, 默认字段全 0.
        """
        return cls(id="am_1")

    def assets_value(self, price: float) -> float:
        """总资产市值 = 现金池 + 持仓市值.

        Args:
            price: float, 当前股票指数价格 (用于估持仓).

        Returns:
            float: 资产端总市值. 注意: 资管无独立资本, sum_assets ==
                sum_liabilities + 0 (NAV 由份额分摊, 不是 NW).
        """
        return self.deposits + self.stock_units * price

    def nav(self, price: float) -> float:
        """单位基金净值 NAV = 总资产 / 已发行份额. 未发行时锚指数价.

        Args:
            price: float, 当前股票价格.

        Returns:
            float: NAV. 当 ``fund_units_outstanding`` 极小或为 0 时
                返回 ``price`` (尚未发行的退化情形, 与指数同步).
        """
        if self.fund_units_outstanding <= 1e-9:
            return price                                # 未发行按指数价锚
        return self.assets_value(price) / self.fund_units_outstanding

    def issue_fund_units(self, value: float, price: float) -> float:
        """申购 value 元, 返回新发份额数."""
        nav = max(self.nav(price), 1e-9)
        units = value / nav
        self.fund_units_outstanding += units
        return units

    def redeem_units(self, fund_units: float, price: float) -> float:
        """赎回若干基金份额, 返回应付金额 (调用方须保证现金充足)."""
        nav = max(self.nav(price), 1e-9)
        amount = min(fund_units, self.fund_units_outstanding) * nav
        self.fund_units_outstanding = max(
            0.0, self.fund_units_outstanding - fund_units
        )
        return amount
