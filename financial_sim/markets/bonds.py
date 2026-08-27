"""债券市场 (Phase 3 前置批次 P0-b).

设计动机 (IMP LEMENTATION.md §5.0 P0-b):
关闭 Phase 2 的简化 "财政赤字 100% CB 承接" — 引入私人部门持债渠道,
让债券价格 / 收益率内生于经济, 同时让央行 OMO 仍可作为最后贷款人.

简化范围:
- 单一期限 (永久债近似, 利率 = policy_rate). 期限分层留 Phase 3 Week A.
- 拍卖: 按"持有人 deposits 占 GDP 比例"分配新债 (隐含"按财富分配").
- 二级市场: 暂不实现 (持有到到期, 没有 capital gain). 留 Phase 3 Week A.
- 不建模价格: 票面价 = 发行价, 利率用 policy_rate (Phase 3+ 引入
  Nelson-Siegel / 期限结构).

SFC 注记:
- 发债: gov.debt ↑F / gov.treasury_deposits ↑F (政府拿到现金)
        cb.treasury_deposits ↑F (CB 负债端)
        households.bonds ↑F / banks.gov_bonds_held ↑F (持有人资产端)
        hh.deposits ↓F / bank.deposits_from_hh ↓F (买家用存款买债)
- 付息: gov.treasury_deposits ↓I / cb.treasury_deposits ↓I
        holders.bonds 账户不变 (本金不动), 收息方 deposits ↑ / 银行 L ↑.
- 到期: 简化 — 假设永续, 不摊销本金; 存量随发债累积.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BondMarket:
    """聚合债券市场.

    字段:
    - outstanding: 当前未偿付国债总面值
    - coupon_rate: 年化票息率 (= policy_rate 简化)
    - holders: {holder_id: 持有面值} 字典; 简化用 household/bank 字典键
    """

    outstanding: float = 0.0
    coupon_rate: float = 0.025  # 默认与 cb_policy_rate_initial 一致
    holders: dict[str, float] = field(default_factory=dict)

    def monthly_interest_due(self) -> float:
        """当月应付利息总额 = 未偿 × 票息率 / 12."""
        return self.outstanding * self.coupon_rate / 12.0

    def issue(self, amount: float, allocations: dict[str, float]) -> None:
        """发行新债: outstanding ↑, 持有人按 allocations 分配.

        Parameters
        ----------
        amount : float
            发行总额 (面值)
        allocations : dict
            {holder_id: amount} 分配表. 调用方负责把 amount 从买家存款转到
            政府 treasury, 此函数只更新市场簿记.
        """
        if amount <= 0:
            return
        self.outstanding += amount
        for hid, amt in allocations.items():
            self.holders[hid] = self.holders.get(hid, 0.0) + amt

    def pay_interest(self, allocations: dict[str, float]) -> None:
        """付息: outstanding 不变 (永续债), 把利息按 allocations 分给持有人.

        调用方负责把相应金额从 gov.treasury_deposits 转到 holders 各自的
        存款账户. 此函数只更新 holders 的应收利息累计 (用于教学诊断).
        """
        for hid in allocations:
            self.holders[hid] = self.holders.get(hid, 0.0)  # 占位, 不动 holdings

    def holder_share(self, hid: str) -> float:
        """某持有人的持债比例."""
        if self.outstanding <= 0:
            return 0.0
        return self.holders.get(hid, 0.0) / self.outstanding


__all__ = ["BondMarket"]
