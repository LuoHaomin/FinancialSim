"""商品市场: 价格调整 + 库存缓冲 (Phase 0 简化)."""
from __future__ import annotations

from financial_sim.core.state import SimulationState


class GoodsMarket:
    """商品市场: 库存缓冲的价格调整 (Phase 3: 逐企业).

    机制 (每家企业独立):
    - 销量口径: firm.last_sales (上月实际销量, step 层写入); 未记录时回退 0
    - 库存目标 = 1 个月销量
    - 库存 > 1.5 倍目标 → 降价 5%; < 0.5 倍目标 → 提价 5%
    - 必须在生产补充库存之后调用 (step 层保证顺序)

    Phase 1 加入:
    - 卡尔沃定价 (firm.calvo_price_prob > 0 时由 step 调用)
    """

    INVENTORY_TARGET_MONTHS = 1.0
    PRICE_ADJUSTMENT = 0.05
    INVENTORY_HIGH_RATIO = 1.5
    INVENTORY_LOW_RATIO = 0.5

    def clear(self, state: SimulationState) -> None:
        """基于月末库存/上月销量的价格调整 (逐企业)."""
        for firm in state.firms:
            monthly_sales = float(getattr(firm, "last_sales", 0.0) or 0.0)
            if monthly_sales <= 0:
                continue

            inventory_target = self.INVENTORY_TARGET_MONTHS * monthly_sales
            inventory_ratio = firm.inventory / inventory_target

            if inventory_ratio > self.INVENTORY_HIGH_RATIO:
                # 过剩 → 降价
                firm.price *= 1 - self.PRICE_ADJUSTMENT
            elif inventory_ratio < self.INVENTORY_LOW_RATIO:
                # 短缺 → 提价
                firm.price *= 1 + self.PRICE_ADJUSTMENT

    def update_inventory(self, state: SimulationState) -> None:
        """补充库存: 期末库存 = 期初 + 生产 − 销量 (逐企业)."""
        for firm in state.firms:
            produced = firm.production()
            sold = float(getattr(firm, "last_sales", 0.0) or 0.0)
            firm.inventory = max(0.0, firm.inventory + produced - sold)
