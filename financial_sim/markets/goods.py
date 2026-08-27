"""商品市场: 价格调整 + 库存缓冲 (Phase 0 简化)."""
from __future__ import annotations

from financial_sim.core.state import SimulationState


class GoodsMarket:
    """Phase 0: 简单商品市场.

    机制:
    - 库存目标 = 1 个月销量
    - 库存 > 1.5 倍目标 → 降价 5%
    - 库存 < 0.5 倍目标 → 提价 5%
    - 其他情况 → 价格不变

    Phase 1 加入:
    - 卡尔沃定价 (Calvo 1983): (1-θ) 概率调价
    - 多部门 firm 各自的库存和价格
    """

    INVENTORY_TARGET_MONTHS = 1.0
    PRICE_ADJUSTMENT = 0.05
    INVENTORY_HIGH_RATIO = 1.5
    INVENTORY_LOW_RATIO = 0.5

    def clear(self, state: SimulationState) -> None:
        """Phase 0: 简单的库存-价格反馈."""
        firm = state.firm
        if firm is None:
            return

        # 估算当月销量
        monthly_sales = state.total_consumption()

        # 库存目标
        inventory_target = self.INVENTORY_TARGET_MONTHS * monthly_sales

        if inventory_target <= 0:
            return

        inventory_ratio = firm.inventory / inventory_target

        if inventory_ratio > self.INVENTORY_HIGH_RATIO:
            # 过剩 → 降价
            firm.price *= 1 - self.PRICE_ADJUSTMENT
        elif inventory_ratio < self.INVENTORY_LOW_RATIO:
            # 短缺 → 提价
            firm.price *= 1 + self.PRICE_ADJUSTMENT

    def update_inventory(self, state: SimulationState) -> None:
        """补充库存: 期末库存 = 期初 + 生产 - 销量."""
        firm = state.firm
        if firm is None:
            return

        produced = firm.production()
        sold = state.total_consumption()
        firm.inventory = max(0.0, firm.inventory + produced - sold)
