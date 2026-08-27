"""交叉持股网络 (Phase 3 Week C M3 骨架).

Barabási–Albert 风格优先连接生成持股图: 老节点(度数高)被更多企业持有.

分配约定 (与 IPO 的"既存资产置换"同一 SFC 简化):
  每家发行人将 `beta` 比例的股数划给其他企业认购, 家庭只认购剩余部分
  — 初始不动任何银行科目, 总供给守恒.

估值约定 (SFC 双科目镜像):
  持有方: 市值计入资产端 FirmBalanceSheet.stocks
  发行方: 同额计入负债端 FirmBalanceSheet.minority_equity
  守恒不变量: Σ持有市值 == Σ被持市值 (每一单位既是某家的资产也是某家的
  负债), 部门聚合 NW 不变, 无双重计算.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class CrossHoldingsNetwork:
    """企业间持股关系: holder_id -> {issuer_id: units}."""

    edges: dict[str, dict[str, float]] = field(default_factory=dict)
    beta: float = 0.2                       # 发行人划给企业股东的比例

    def held_units(self, holder_id: str) -> dict[str, float]:
        return self.edges.get(holder_id, {})

    def valuation(self, holder_id: str, prices: dict[str, float]) -> float:
        """持有方的持股市值."""
        return sum(
            u * prices.get(issuer, 0.0)
            for issuer, u in self.edges.get(holder_id, {}).items()
        )

    @property
    def total_units(self) -> float:
        return sum(u for tgt in self.edges.values() for u in tgt.values())

    def issued_units_to_firms(self) -> dict[str, float]:
        """各发行人已发行到企业股东名下的股数."""
        issued: dict[str, float] = {}
        for targets in self.edges.values():
            for issuer_id, u in targets.items():
                issued[issuer_id] = issued.get(issuer_id, 0.0) + u
        return issued


def build_cross_holdings(
    firms: list,
    beta: float,
    rng: np.random.Generator,
    m_links: int = 2,
) -> CrossHoldingsNetwork:
    """为企业列表生成交叉持股 (发行人视角的优先连接).

    算法: 按输入顺序逐个成为"发行人", 从已有节点中按累计度数加权抽
    m_links 个持有人分掉自己 beta×shares 的股数; 头部节点互相持有形成环.
    """
    n = len(firms)
    net = CrossHoldingsNetwork(beta=float(beta))
    if n < 2 or beta <= 0:
        return net

    degrees = {f.id: 1 for f in firms}      # 初始均匀权重
    ids = [f.id for f in firms]

    for issuer_pos, issuer in enumerate(firms):
        giveaway = float(issuer.shares_outstanding) * float(beta)
        if giveaway <= 0:
            continue
        candidates = ids[:issuer_pos] + ids[issuer_pos + 1:]
        if not candidates:
            continue
        m = min(max(1, int(m_links)), len(candidates))
        weights = np.array([degrees[cid] for cid in candidates], dtype=float)
        probs = weights / weights.sum()
        picks = rng.choice(len(candidates), size=m, replace=False, p=probs)
        # 均分 giveaway 给被选中的持有人
        per = giveaway / m
        residue_distribution = per * m
        for pos in picks:
            holder_id = candidates[int(pos)]
            net.edges.setdefault(holder_id, {})
            net.edges[holder_id][issuer.id] = (
                net.edges[holder_id].get(issuer.id, 0.0) + per
            )
            degrees[holder_id] += 1
            degrees[issuer.id] += m         # 反向耦合增强成环概率
        assert residue_distribution > 0
    return net
