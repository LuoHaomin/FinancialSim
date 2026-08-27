"""Tests for Stock-Flow Consistency (SFC) validator.

SFC 的核心: 同笔钱在两个部门必须有同样的记账.
- HH 的存款 = 银行的存款负债
- HH 的现金 = CB 发行的现金
- 银行准备金 = CB 持有的银行准备金
- 政府发行的国债 = 银行 + CB + 其他持有的国债

Phase 0 检查项目:
1. 每个部门的 BS 恒等式 (A = L + NW)
2. 银行不变量 (A = L + capital, 因为 NW = capital)
3. CB 不变量 (同上)
4. 跨部门存款一致性
5. 跨部门现金/准备金一致性

TDD: 写在实现前.
"""
from __future__ import annotations

from financial_sim.monetary.balance_sheets import (
    CentralBankBalanceSheet,
    CommercialBankBalanceSheet,
    FirmBalanceSheet,
    GovernmentBalanceSheet,
    HouseholdBalanceSheet,
)
from financial_sim.monetary.sfc import validate_sfc

EPSILON = 1e-6


def make_balanced_economy() -> dict[str, object]:
    """构造一个内部平衡的虚拟经济.

    所有跨部门债权债务互相抵消.
    不变量自检:
        Banks.A = 6300, Banks.L = 6000, Banks.capital = 300
        CB.A    = 3000, CB.L    = 1600, CB.capital    = 1400
        现金: HH(500) + Firms(300) = CB.currency_issued(800)
        存款: HH(4000) + Firms(2000) = Bank.deposits(4000+2000)
        准备金: Bank.reserves(800) = CB.bank_reserves(800)
        债券: Bank.bonds(500) + CB.gov_bonds(3000) = Gov.outstanding(3500)
    """
    return {
        "households": HouseholdBalanceSheet(
            cash=500,
            deposits=4000,
            stocks=1000,
            housing_self=10000,
            mortgage=2000,
        ),
        "firms": FirmBalanceSheet(
            cash=300,
            deposits=2000,
            inventories=2000,
            capital_stock=15000,
            interfirm_claims=500,
            bank_loans=3000,
            accounts_payable=500,
        ),
        "banks": CommercialBankBalanceSheet(
            reserves=800,
            loans_to_firms=3000,
            loans_to_households=2000,
            gov_bonds_held=500,
            interbank_claims=0,
            deposits_from_hh=4000,
            deposits_from_firms=2000,
            interbank_debt=0,
            bonds_issued=0,
            capital=300,  # 资本 = 资产 - 负债 = 6300 - 6000
        ),
        "government": GovernmentBalanceSheet(
            treasury_deposits=100,
            other_assets=50,
            bonds_outstanding=3500,
        ),
        "cb": CentralBankBalanceSheet(
            gov_bonds=3000,
            lolr_claims=0,
            other_assets=0,
            bank_reserves=800,
            currency_issued=800,
            capital=1400,  # 资本 = 资产 - 负债 = 3000 - 1600
        ),
    }


class TestBalancedEconomyPasses:
    """一个平衡的经济不应触发任何 SFC 错误."""

    def test_balanced_economy_no_errors(self):
        bs = make_balanced_economy()
        errors = validate_sfc(bs)
        assert errors == [], f"Expected no SFC errors, got: {errors}"

    def test_each_sector_bs_identity_holds(self):
        """每个部门自己的 BS 恒等式 A = L + NW."""
        bs = make_balanced_economy()
        errors = validate_sfc(bs)
        assert not any("identity" in e.lower() for e in errors)


class TestBSIdentityCatchesViolations:
    """人为破坏 BS 恒等式, 应触发错误.

    注意: 对于 NW 字段是 computed property 的部门 (HH/Firm/Gov),
    A = L + NW 是恒等成立的. 要触发错误必须通过跨部门一致性检查.
    对于 NW 是独立字段的部门 (Bank/CB), A = L + NW 是真正的约束.
    """

    def test_breaking_household_causes_error(self):
        """HH 增加现金但 CB 没对应, 应被检测."""
        bs = make_balanced_economy()
        bs["households"].cash += 100
        errors = validate_sfc(bs)
        # 错误必然来自 cash mismatch (HH 现金多出, CB 没对应)
        assert any("cash" in e.lower() for e in errors), (
            f"Expected cash-related violation, got: {errors}"
        )

    def test_breaking_firm_causes_error(self):
        bs = make_balanced_economy()
        bs["firms"].deposits += 100  # 凭空多 100 存款, 银行没对应
        errors = validate_sfc(bs)
        # 触发 deposit mismatch
        assert any("deposit" in e.lower() for e in errors)

    def test_breaking_bank_invariant_detected(self):
        """银行的 NW = capital 是独立字段, 故可被破坏."""
        bs = make_balanced_economy()
        bs["banks"].loans_to_firms += 100  # 资产多了, 资本没变
        errors = validate_sfc(bs)
        assert any("banks" in e.lower() or "identity" in e.lower() for e in errors)

    def test_breaking_cb_invariant_detected(self):
        """CB 的 NW = capital 是独立字段, 故可被破坏."""
        bs = make_balanced_economy()
        bs["cb"].gov_bonds += 100
        errors = validate_sfc(bs)
        assert any("cb" in e.lower() or "identity" in e.lower() for e in errors)

    def test_breaking_government_causes_error(self):
        bs = make_balanced_economy()
        bs["government"].bonds_outstanding += 100  # 多发 100 国债, 无人持有
        errors = validate_sfc(bs)
        assert any("bond" in e.lower() for e in errors)


class TestCrossSectorConsistency:
    """跨部门一致性: 同笔钱必须两边记账相同."""

    def test_household_deposits_must_match_bank_deposits_from_hh(self):
        bs = make_balanced_economy()
        # HH 说存了 4000, 银行说欠 HH 4000
        # 人为制造不一致
        bs["households"].deposits += 100
        errors = validate_sfc(bs)
        assert any("deposit" in e.lower() for e in errors), (
            f"Expected deposit mismatch, got: {errors}"
        )

    def test_firm_deposits_must_match_bank_deposits_from_firms(self):
        bs = make_balanced_economy()
        bs["firms"].deposits += 50
        errors = validate_sfc(bs)
        assert any("deposit" in e.lower() for e in errors)

    def test_bank_reserves_must_match_cb_bank_reserves(self):
        bs = make_balanced_economy()
        bs["banks"].reserves += 25
        errors = validate_sfc(bs)
        assert any("reserve" in e.lower() for e in errors), (
            f"Expected reserve mismatch, got: {errors}"
        )

    def test_cash_held_must_match_currency_issued(self):
        """HH + Firms 持有的现金 = CB 发行的现金."""
        bs = make_balanced_economy()
        bs["households"].cash += 50  # 多出来的现金没有 CB 对应
        errors = validate_sfc(bs)
        assert any("cash" in e.lower() or "currency" in e.lower() for e in errors)

    def test_gov_bonds_outstanding_must_match_holdings(self):
        """政府发行的国债 = 银行 + CB 持有的国债."""
        bs = make_balanced_economy()
        bs["government"].bonds_outstanding += 200  # 多发 200, 无人持有
        errors = validate_sfc(bs)
        assert any("bond" in e.lower() for e in errors)


class TestSFCReturnsList:
    """SFC 应返回错误列表, 不抛出异常 (除非调用方要求)."""

    def test_returns_list_type(self):
        bs = make_balanced_economy()
        result = validate_sfc(bs)
        assert isinstance(result, list)

    def test_empty_list_for_balanced_state(self):
        bs = make_balanced_economy()
        result = validate_sfc(bs)
        assert result == []

    def test_multiple_errors_reported(self):
        bs = make_balanced_economy()
        bs["households"].cash += 100
        bs["firms"].deposits += 100
        bs["banks"].reserves += 100
        errors = validate_sfc(bs)
        # 应该至少 3 个错误
        assert len(errors) >= 3
