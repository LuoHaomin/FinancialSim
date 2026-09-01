"""Interbank network (Phase 2).

设计 (DESIGN.md §2.2 决策 #11 + AGENTS.md §3.4.5):
- Core-Periphery 拓扑: 核心银行之间紧密互联, 外围银行连接到核心
- 简化: 用邻接字典 {(bank_a_id, bank_b_id): exposure_amount}
- 不在仿真中显式模拟拆借利率, 用占位 amount 表示敞口

SFC 注记: 同业拆借的初始化与演化在 step._interbank_cycle 完成.
当银行失败时, 其同业拆入的债权方会承担损失 (Phase 2.4 fire-sale).

Phase 3.5 PR-4: 动态化
- `rewire(banks, rng)`: 季度重连 (按 CAR 重排核心/外围)
- `rebalance_reserves(banks, target, tolerance)`: 每 tick 检测
   reserves/deposits 比例, 偏离时经同业市场调拨
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass
class InterbankNetwork:
    """Phase 2 + Phase 3.5 PR-4 银行间网络: Core-Periphery + 动态重连."""

    exposures: dict[tuple[str, str], float] = field(default_factory=dict)
    core_ids: list[str] = field(default_factory=list)
    last_rewire_t: int = -1  # 上次 rewire 的 tick (防止重复触发)

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

    def rewire(
        self,
        banks: list,
        core_size: int,
        link_density: float,
        avg_exposure: float,
        rng: random.Random,
        current_t: int,
    ) -> None:
        """季度重连 (PR-4 动态化).

        1. 按 CAR 重新划分核心/外围 (CAR 最高的 core_size 家进核心)
        2. 清空旧敞口
        3. 用相同构造规则重连 (build_core_periphery 逻辑内联)
        4. 同步银行的 interbank_claims/debt (旧的拆, 新的建)

        SFC: 每笔敞口 lender=bank_A 加 interbank_claims,
              borrower=bank_B 加 interbank_debt (一笔对应两侧).
        Σ 双向敞口同步归零再重建, 聚合 SFC 守恒.
        """
        if current_t == self.last_rewire_t:
            return  # 防止同 tick 重复
        self.last_rewire_t = current_t

        # 0. 清空银行侧同业账目
        for b in banks:
            b.interbank_claims = 0.0
            b.interbank_debt = 0.0

        # 1. 按 CAR 重排核心 (跳过 failed + inf)
        alive = [
            b for b in banks
            if not b.is_failed and b.car() != float("inf")
        ]
        alive.sort(key=lambda b: b.car(), reverse=True)
        core = [b.id for b in alive[:core_size]]
        periphery = [b.id for b in banks if b.id not in core]

        # 2. 清空旧敞口, 重置 core_ids
        self.exposures.clear()
        self.core_ids = core

        if not core:
            return

        # 3. 重建 Core-Periphery 拓扑
        # 核心内部全连接
        for i, b1 in enumerate(core):
            for b2 in core[i + 1:]:
                amt = avg_exposure * rng.uniform(0.5, 1.5)
                self.exposures[(b1, b2)] = amt
                self.exposures[(b2, b1)] = amt

        # 外围 → 核心
        for p in periphery:
            for c in core:
                if rng.random() < link_density:
                    amt = avg_exposure * rng.uniform(0.3, 1.0)
                    self.exposures[(c, p)] = amt

        # 4. 同步银行侧敞口
        bank_by_id = {b.id: b for b in banks}
        for (creditor_id, debtor_id), amt in self.exposures.items():
            cred = bank_by_id.get(creditor_id)
            debe = bank_by_id.get(debtor_id)
            if cred is not None and debe is not None:
                cred.interbank_claims += amt
                debe.interbank_debt += amt

    def rebalance_reserves(
        self,
        banks: list,
        target_ratio: float,
        tolerance: float,
        cb: object | None = None,
    ) -> tuple[int, float]:
        """每 tick 储备再平衡.

        检测每家银行的 reserves/deposits 比例, 偏离时通过**CB 中介**调拨:
          - reserves 不足: 银行向 CB 拆入 (reserves ↑, CB.bank_reserves ↑,
            bank.interbank_debt ↑, CB.bank_reserves (CB视角的负债) ↑)
          - reserves 过多: 银行向 CB 拆出 (反向)

        简化: 通过 CB 中介 (而非银行间直拆) 保证 Σ reserves 镜像.
        SFC: 聚合 Σ bank.reserves == CB.bank_reserves 保持 (双向同步).
        cb 传 None 时, 单边调整 (可能破坏 SFC; 仅测试用).

        Returns
        -------
        (n_moves, total_net_injection)
            n_moves: 实际调拨银行数
            total_net_injection: CB 视角的总注入 (+ 拆出 - 拆入)
        """
        moves = 0
        net_to_cb = 0.0
        for b in banks:
            if b.is_failed:
                continue
            deposits_total = (
                b.deposits_from_hh + b.deposits_from_firms
                + getattr(b, "deposits_from_nbfi", 0.0)
            )
            if deposits_total <= 1e-9:
                continue
            current_ratio = b.reserves / deposits_total
            deviation = current_ratio - target_ratio
            if abs(deviation) <= tolerance:
                continue
            # 调拨量: 把比例拉到 target (最大 10% deposits / tick, 风控)
            max_move = deposits_total * 0.10
            target_reserves = target_ratio * deposits_total
            move = target_reserves - b.reserves
            move = max(-max_move, min(max_move, move))
            if abs(move) < 1e-9:
                continue
            if move > 0:
                # 向 CB 拆入: reserves ↑I / interbank_debt ↑I
                # CB 镜像: bank_reserves ↑I (CB 创造了准备金)
                #         cb.capital ↓I (匹配 IOR 模式, SFC 守恒)
                b.reserves += move
                b.interbank_debt += move
                if cb is not None:
                    cb.bank_reserves += move
                    cb.capital -= move
                    net_to_cb += move
            else:
                # 向 CB 拆出: reserves ↓ / interbank_claims ↑
                # CB 镜像: bank_reserves ↓ (CB 收回了准备金)
                #         cb.capital ↑ (反向 IOR)
                b.reserves += move
                b.interbank_claims += -move
                if cb is not None:
                    cb.bank_reserves += move
                    cb.capital += -move
                    net_to_cb += move
            moves += 1
        return moves, net_to_cb

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
