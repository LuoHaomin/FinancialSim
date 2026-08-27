"""Stock-Flow Consistency (SFC) validator.

SFC 核心: 每笔钱在两个部门必须有同样的记账. 违反 SFC 意味着钱凭空产生/消失.

Phase 0 检查项:
1. 每个部门 BS 恒等式: A = L + NW (银行/CB: A = L + capital)
2. 跨部门存款一致性 (HH/Firms 存款 = 银行的存款负债)
3. 跨部门准备金一致性 (银行准备金 = CB 持有的银行准备金)
4. 跨部门现金一致性 (HH+Firms 现金 = CB 发行的现金)
5. 政府债券发行与持有的一致性

设计文档 §5.3.3 中的"money_supply == money_uses"公式仅在 bank.capital = 0 且
无现金时成立. 这里用更直接的跨部门一致性检查 (本质上等价但更稳健).
"""
from __future__ import annotations

from typing import Any

EPSILON_ABS = 1e-6


def _tolerance(*magnitudes: float) -> float:
    """相对容差: 大数量级下浮点累积误差按比例放宽.

    ~1e4 的量级允许 ~1e-5 的绝对误差 (相对 1e-9).
    """
    scale = max(abs(m) for m in magnitudes) if magnitudes else 0.0
    return max(EPSILON_ABS, 1e-9 * scale)


class SFCViolationError(Exception):
    """SFC 校验失败时抛出.

    生产环境应在仿真每 tick 调用 validate_sfc, 收到错误列表后:
    - 立即停止仿真
    - 保存违反状态快照 (用于调试)
    - 抛出此异常
    """

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"{len(errors)} SFC violation(s): {'; '.join(errors[:3])}")


def validate_sfc(balance_sheets: dict[str, Any]) -> list[str]:
    """校验 Stock-Flow Consistency.

    Parameters
    ----------
    balance_sheets : dict
        键: 'households' / 'firms' / 'banks' / 'government' / 'cb'
        值: 对应的 BS dataclass 实例

    Returns
    -------
    list[str]
        错误信息列表. 空列表 = 通过.
    """
    errors: list[str] = []

    hh = balance_sheets.get("households")
    f = balance_sheets.get("firms")
    b = balance_sheets.get("banks")
    gov = balance_sheets.get("government")
    cb = balance_sheets.get("cb")

    # ─── 1. BS 恒等式: A = L + NW ───
    for name, sheet in balance_sheets.items():
        if sheet is None:
            continue
        a = sheet.sum_assets()
        liab = sheet.sum_liabilities()
        nw = sheet.net_worth
        delta = a - liab - nw
        if abs(delta) > _tolerance(a, liab):
            errors.append(
                f"BS identity violation: {name} "
                f"A={a:.4f} L={liab:.4f} NW={nw:.4f} Δ={delta:.6f}"
            )

    # ─── 2. 跨部门: 存款 ───
    if hh is not None and b is not None:
        diff = hh.deposits - b.deposits_from_hh
        if abs(diff) > _tolerance(hh.deposits, b.deposits_from_hh):
            errors.append(
                f"Deposit mismatch (HH): HH.deposits={hh.deposits} "
                f"!= Banks.deposits_from_hh={b.deposits_from_hh} Δ={diff:.4f}"
            )

    if f is not None and b is not None:
        diff = f.deposits - b.deposits_from_firms
        if abs(diff) > _tolerance(f.deposits, b.deposits_from_firms):
            errors.append(
                f"Deposit mismatch (Firms): Firms.deposits={f.deposits} "
                f"!= Banks.deposits_from_firms={b.deposits_from_firms} Δ={diff:.4f}"
            )

    # ─── 3. 跨部门: 准备金 ───
    if b is not None and cb is not None:
        diff = b.reserves - cb.bank_reserves
        if abs(diff) > _tolerance(b.reserves, cb.bank_reserves):
            errors.append(
                f"Reserve mismatch: Banks.reserves={b.reserves} "
                f"!= CB.bank_reserves={cb.bank_reserves} Δ={diff:.4f}"
            )

    # ─── 4. 跨部门: 现金 ───
    if hh is not None and f is not None and cb is not None:
        cash_held = hh.cash + f.cash
        diff = cash_held - cb.currency_issued
        if abs(diff) > _tolerance(cash_held, cb.currency_issued):
            errors.append(
                f"Cash mismatch: HH+Firms cash={cash_held} "
                f"!= CB.currency_issued={cb.currency_issued} Δ={diff:.4f}"
            )

    # ─── 5. 政府债券: 发行 = 持有 ───
    if gov is not None and b is not None and cb is not None:
        held = b.gov_bonds_held + cb.gov_bonds
        diff = held - gov.bonds_outstanding
        if abs(diff) > _tolerance(held, gov.bonds_outstanding):
            errors.append(
                f"Bond mismatch: Banks+CB holdings={held} "
                f"!= Gov.bonds_outstanding={gov.bonds_outstanding} Δ={diff:.4f}"
            )

    return errors
