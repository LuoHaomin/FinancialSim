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
    # 成本加成锚 (校准 2026-08): 纯库存规则的 价格是随机游走, 且库存平滑
    # 导致低价月触发降价的频率系统性高于涨价的频率 → 基线通缩螺旋
    # (实测 60 月价格 -88%, 企业慢性亏损破产). 锚定到单位劳动成本
    # 使通胀趋势跟随工资增长 − 生产率增长, 库存信号只做短期扰动.
    MARKUP_TARGET = 0.10          # 目标成本加成 μ
    ANCHOR_PULL = 0.25            # 过剩时向锚收敛的速度 (每月)
    DRIFT_PULL = 0.02             # 中性区间缓慢回归锚

    def _cost_anchor(self, firm) -> float | None:
        """目标价 = (1+μ)·单位可变成本 (线性技术下 = w/A)."""
        wage = float(getattr(firm, "wage_offered", 0.0) or 0.0)
        productivity = float(getattr(firm, "productivity", 0.0) or 0.0)
        if productivity <= 0:
            return None
        return (1.0 + self.MARKUP_TARGET) * wage / productivity

    def clear(self, state: SimulationState) -> None:
        """基于月末库存/上月销量的价格调整 (逐企业, 成本加成锚定)."""
        for firm in state.firms:
            monthly_sales_value = float(getattr(firm, "last_sales", 0.0) or 0.0)
            if monthly_sales_value <= 0:
                continue

            # last_sales 是金额; 库存是数量 → 换算成月销数量再比.
            inventory_target = (
                self.INVENTORY_TARGET_MONTHS * monthly_sales_value / firm.price
            )
            inventory_ratio = firm.inventory / inventory_target

            anchor = self._cost_anchor(firm)
            if anchor is None or anchor <= 0:
                continue

            if inventory_ratio > self.INVENTORY_HIGH_RATIO:
                # 过剩 → 降价, 下限 = 锚×(1−浮动带). 完全刚性成本下限会
                # 与需求侧流量恒等冲突 (购买力买不起加成价 → 库存永远过剩
                # → 债务复利), 故允许有限度的亏损带.
                target = max(
                    anchor * 0.90,
                    firm.price * (1 - self.PRICE_ADJUSTMENT),
                )
                firm.price += self.ANCHOR_PULL * (target - firm.price)
            elif inventory_ratio < self.INVENTORY_LOW_RATIO:
                # 短缺 → 提价 (受锚上方的温和约束防止棘轮失控)
                ceiling = max(anchor * 1.25, firm.price)
                firm.price = min(
                    ceiling,
                    firm.price * (1 + self.PRICE_ADJUSTMENT),
                )
            else:
                # 中性区间: 缓慢回归成本锚
                firm.price += self.DRIFT_PULL * (anchor - firm.price)

    def update_inventory(self, state: SimulationState) -> None:
        """补充库存: 期末库存 = 期初 + 生产 − 销量 (逐企业)."""
        for firm in state.firms:
            produced = firm.production()
            sold = float(getattr(firm, "last_sales", 0.0) or 0.0)
            firm.inventory = max(0.0, firm.inventory + produced - sold)
