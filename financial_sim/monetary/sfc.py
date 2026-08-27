"""Stock-Flow Consistency (SFC) validator.

SFC 核心: 每笔钱在两个部门必须有同样的记账. 违反 SFC 意味着钱凭空产生/消失.

检查项:
1. 每个部门 BS 恒等式: A = L + NW (银行/CB: A = L + capital)
2. 跨部门存款一致性 (HH/Firms 存款 = 银行的存款负债)
3. 跨部门准备金一致性 (银行准备金 = CB 持有的银行准备金)
4. 跨部门现金一致性 (HH+Firms 现金 = CB 发行的现金)
5. 政府债券发行与持有的一致性 (HH + 银行 + CB 持有 = 发行)
6. 家庭贷款一致性 (房贷 + 消费贷 = 银行对家庭的贷款资产)
7. 企业贷款一致性 (企业银行借款 = 银行对企业的贷款资产)
8. 财政部存款一致性 (政府 treasury 存款 = CB 的 treasury 负债)

设计文档 §5.3.3 中的"money_supply == money_uses"公式仅在 bank.capital = 0 且
无现金时成立. 这里用更直接的跨部门一致性检查 (本质上等价但更稳健).

⚠️ 6/7/8 项是 Phase 3 前置批次新增: 在此之前家庭负债、企业贷款、财政部存款
都在校验范围之外 — 一侧漂移不会被发现. 新增任何"银行对某部门的债权"字段时,
必须在此同步加一项跨部门检查, 否则该资产等于无人对账.
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

    # ─── 5. 政府债券: 发行 = 持有 (HH + 银行 + CB) ───
    if gov is not None and b is not None and cb is not None:
        hh_bonds = hh.bonds if hh is not None else 0.0
        held = b.gov_bonds_held + cb.gov_bonds + hh_bonds
        diff = held - gov.bonds_outstanding
        if abs(diff) > _tolerance(held, gov.bonds_outstanding):
            errors.append(
                f"Bond mismatch: HH+Banks+CB holdings={held} "
                f"!= Gov.bonds_outstanding={gov.bonds_outstanding} Δ={diff:.4f}"
            )

    # ─── 6. 家庭贷款: 家庭负债 = 银行对家庭债权 ───
    if hh is not None and b is not None:
        hh_loans = hh.mortgage + hh.consumer_loan + hh.other_debt
        diff = hh_loans - b.loans_to_households
        if abs(diff) > _tolerance(hh_loans, b.loans_to_households):
            errors.append(
                f"HH loan mismatch: HH liabilities={hh_loans} "
                f"!= Banks.loans_to_households={b.loans_to_households} Δ={diff:.4f}"
            )

    # ─── 7. 企业贷款: 企业负债 = 银行对企业债权 ───
    if f is not None and b is not None:
        diff = f.bank_loans - b.loans_to_firms
        if abs(diff) > _tolerance(f.bank_loans, b.loans_to_firms):
            errors.append(
                f"Firm loan mismatch: Firms.bank_loans={f.bank_loans} "
                f"!= Banks.loans_to_firms={b.loans_to_firms} Δ={diff:.4f}"
            )

    # ─── 8. 财政部存款: 政府资产 = CB 负债 ───
    if gov is not None and cb is not None:
        cb_treasury = getattr(cb, "treasury_deposits", 0.0)
        diff = gov.treasury_deposits - cb_treasury
        if abs(diff) > _tolerance(gov.treasury_deposits, cb_treasury):
            errors.append(
                f"Treasury deposit mismatch: Gov.treasury_deposits="
                f"{gov.treasury_deposits} != CB.treasury_deposits={cb_treasury} "
                f"Δ={diff:.4f}"
            )

    # ─── 9. NBFI 存款一致性 (Week D: 投行+资管在商行的存款) ───
    ib = balance_sheets.get("investment_bank")
    am = balance_sheets.get("asset_manager")
    if b is not None and (ib is not None or am is not None):
        nbfi_dep = (
            (ib.deposits if ib is not None else 0.0)
            + (am.deposits if am is not None else 0.0)
        )
        mirror = getattr(b, "deposits_from_nbfi", 0.0)
        diff = nbfi_dep - mirror
        if abs(diff) > _tolerance(nbfi_dep, mirror):
            errors.append(
                f"NBFI deposit mismatch: IB+AM deposits={nbfi_dep} "
                f"!= Banks.deposits_from_nbfi={mirror} Δ={diff:.4f}"
            )

    return errors


def validate_housing_stock(
    units_held_by_households: int,
    units_held_as_reo: int,
    total_units: int,
) -> list[str]:
    """校验实物住房存量守恒: 家庭持有 + 银行止赎 = 市场总量.

    住房是实物资产, 不需要金融对手方, 但**数量必须守恒** — 止赎/甩卖只是
    所有权转移, 不能凭空销毁房屋. 历史 bug: fire-sale 阶段把 REO 计数直接
    归零, 房子人间蒸发.
    """
    errors: list[str] = []
    held = units_held_by_households + units_held_as_reo
    if held != total_units:
        errors.append(
            f"Housing stock mismatch: households={units_held_by_households} "
            f"+ REO={units_held_as_reo} = {held} != total_units={total_units}"
        )
    return errors
