"""Interbank network (Phase 2).

设计 (DESIGN.md §2.2 决策 #11 + AGENTS.md §3.4.5):
- Core-Periphery 拓扑: 核心银行之间紧密互联, 外围银行连接到核心
- 简化: 用邻接字典 {(bank_a_id, bank_b_id): exposure_amount}
- 不在仿真中显式模拟拆借利率, 用占位 amount 表示敞口

SFC 注记: 同业拆借的初始化与演化在 step._interbank_cycle 完成.
当银行失败时, 其同业拆入的债权方会承担损失 (Phase 2.4 fire-sale).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass
class InterbankNetwork:
    """Phase 2 银行间网络: Core-Periphery 拓扑 + 敞口字典.

    字段:
    - exposures: dict, key=(creditor_id, debtor_id), value=敞口金额
      (creditor 借给 debtor, 即 debtor 欠 creditor)
    - core_ids: 核心银行 ID 列表
    """

    exposures: dict[tuple[str, str], float] = field(default_factory=dict)
    core_ids: list[str] = field(default_factory=list)

    @classmethod
    def build_core_periphery(
        cls,
        bank_ids: list[str],
        core_size: int,
        link_density: float,
        avg_exposure: float,
        rng: random.Random | None = None,
    ) -> InterbankNetwork:
        """构造 Core-Periphery 网络.

        - 核心银行: core_size 个, 全部互相连接 (全连接)
        - 外围银行: 每个以 link_density 概率连接到每个核心
        - 敞口金额: avg_exposure × 随机因子 [0.5, 1.5]
        """
        if rng is None:
            rng = random.Random(42)
        network = cls()
        if not bank_ids:
            return network

        core_size = min(core_size, len(bank_ids))
        network.core_ids = bank_ids[:core_size]
        periphery = bank_ids[core_size:]

        # 核心内部全连接
        for i, b1 in enumerate(network.core_ids):
            for b2 in network.core_ids[i + 1:]:
                amt = avg_exposure * rng.uniform(0.5, 1.5)
                network.exposures[(b1, b2)] = amt
                network.exposures[(b2, b1)] = amt  # 对称敞口

        # 外围 → 核心 (单向连接)
        for p in periphery:
            for c in network.core_ids:
                if rng.random() < link_density:
                    amt = avg_exposure * rng.uniform(0.3, 1.0)
                    network.exposures[(c, p)] = amt  # 核心借给外围

        return network

    def creditors_of(self, debtor_id: str) -> list[tuple[str, float]]:
        """返回所有对 debtor 有债权的 (creditor_id, amount) 列表."""
        return [
            (creditor, amount)
            for (creditor, debtor), amount in self.exposures.items()
            if debtor == debtor_id
        ]

    def total_outstanding(self, bank_id: str) -> float:
        """银行的总敞口 (借出 + 借入)."""
        claims = sum(
            amt for (creditor, _), amt in self.exposures.items() if creditor == bank_id
        )
        debts = sum(
            amt for (_, debtor), amt in self.exposures.items() if debtor == bank_id
        )
        return claims + debts

    def apply_failure(
        self, failed_bank_id: str, recovery_rate: float = 0.4
    ) -> dict[str, float]:
        """银行失败: 清算其同业敞口, 债权人按 recovery_rate 回收.

        返回 dict[creditor_id, loss_amount].
        """
        losses: dict[str, float] = {}
        creditors = self.creditors_of(failed_bank_id)
        for creditor_id, amount in creditors:
            recovered = amount * recovery_rate
            loss = amount - recovered
            losses[creditor_id] = losses.get(creditor_id, 0.0) + loss
            # 移除敞口
            del self.exposures[(creditor_id, failed_bank_id)]

        # 失败银行作为债权人/债务人的敞口都已失效
        for key in list(self.exposures.keys()):
            if failed_bank_id in key:
                del self.exposures[key]

        return losses


__all__ = ["InterbankNetwork"]
