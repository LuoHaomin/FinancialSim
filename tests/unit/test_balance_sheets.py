"""Tests for the 5 sector balance sheet classes.

These are the foundation of Stock-Flow Consistency (SFC).
Every transaction MUST respect the BS identity: A = L + NW.

TDD: Written before implementation. Each test describes a contract.
"""
from __future__ import annotations

from financial_sim.monetary.balance_sheets import (
    CentralBankBalanceSheet,
    CommercialBankBalanceSheet,
    FirmBalanceSheet,
    GovernmentBalanceSheet,
    HouseholdBalanceSheet,
)

EPSILON = 1e-9


# ════════════════════════════════════════════════════════════
# HouseholdBalanceSheet
# ════════════════════════════════════════════════════════════
class TestHouseholdBalanceSheet:
    """Household BS: assets + liabilities, NW = A - L."""

    def test_zero_state_satisfies_identity(self):
        bs = HouseholdBalanceSheet()
        assert bs.sum_assets() == 0
        assert bs.sum_liabilities() == 0
        assert bs.net_worth == 0

    def test_typical_state_satisfies_identity(self):
        bs = HouseholdBalanceSheet(
            cash=1000, deposits=5000, stocks=2000, bonds=1000,
            housing_self=30000, housing_investment=0, consumer_durables=5000,
            mortgage=20000, consumer_loan=3000, other_debt=1000,
        )
        expected_assets = 1000 + 5000 + 2000 + 1000 + 30000 + 0 + 5000  # 44000
        expected_liab = 20000 + 3000 + 1000  # 24000
        expected_nw = expected_assets - expected_liab  # 20000

        assert bs.sum_assets() == expected_assets
        assert bs.sum_liabilities() == expected_liab
        assert bs.net_worth == expected_nw

    def test_negative_net_worth_when_overleveraged(self):
        """杠杆破产的家庭: NW 为负。"""
        bs = HouseholdBalanceSheet(
            cash=1000, deposits=0, stocks=0, bonds=0,
            housing_self=30000, housing_investment=0, consumer_durables=0,
            mortgage=35000, consumer_loan=0, other_debt=0,
        )
        assert bs.net_worth == -4000


# ════════════════════════════════════════════════════════════
# FirmBalanceSheet
# ════════════════════════════════════════════════════════════
class TestFirmBalanceSheet:
    """Firm BS: assets + liabilities, NW = A - L."""

    def test_zero_state(self):
        bs = FirmBalanceSheet()
        assert bs.sum_assets() == 0
        assert bs.sum_liabilities() == 0
        assert bs.net_worth == 0

    def test_typical_manufacturing_firm(self):
        bs = FirmBalanceSheet(
            cash=500, deposits=2000, inventories=3000,
            capital_stock=10000, interfirm_claims=500,
            bank_loans=4000, bonds_issued=2000, accounts_payable=1000,
        )
        # A = 16000, L = 7000, NW = 9000
        assert bs.sum_assets() == 16000
        assert bs.sum_liabilities() == 7000
        assert bs.net_worth == 9000

    def test_bankrupt_firm_has_negative_nw(self):
        bs = FirmBalanceSheet(
            cash=100, deposits=0, inventories=500, capital_stock=2000,
            interfirm_claims=0,
            bank_loans=3000, bonds_issued=500, accounts_payable=200,
        )
        # A = 2600, L = 3700, NW = -1100
        assert bs.net_worth == -1100


# ════════════════════════════════════════════════════════════
# CommercialBankBalanceSheet
# ════════════════════════════════════════════════════════════
class TestCommercialBankBalanceSheet:
    """Bank BS: 资本独立追踪. NW = capital 字段.

    关键不变量: sum_assets() == sum_liabilities() + capital
    """

    def test_zero_state(self):
        bs = CommercialBankBalanceSheet()
        assert bs.sum_assets() == 0
        assert bs.sum_liabilities() == 0
        assert bs.net_worth == 0  # capital 默认为 0

    def test_typical_bank_with_balanced_invariant(self):
        bs = CommercialBankBalanceSheet(
            reserves=1000, loans_to_firms=5000, loans_to_households=3000,
            gov_bonds_held=2000, interbank_claims=500,
            deposits_from_hh=8000, deposits_from_firms=1500,
            interbank_debt=400, bonds_issued=600,
            capital=1000,
        )
        # A = 11500, L = 10500, A - L = 1000 = capital
        assert bs.sum_assets() == 11500
        assert bs.sum_liabilities() == 10500
        assert bs.net_worth == 1000  # 等于 capital 字段

    def test_bank_invariant_a_equals_l_plus_capital(self):
        """不变量: A = L + capital. SFC 校验依赖此性质."""
        bs = CommercialBankBalanceSheet(
            reserves=500, loans_to_firms=2000, loans_to_households=1000,
            gov_bonds_held=500, interbank_claims=0,
            deposits_from_hh=2500, deposits_from_firms=500,
            interbank_debt=0, bonds_issued=0,
            capital=1000,
        )
        assert bs.sum_assets() - bs.sum_liabilities() == bs.net_worth

    def test_bank_with_zero_capital_zero_nw(self):
        bs = CommercialBankBalanceSheet(
            reserves=100, loans_to_firms=1000, loans_to_households=0,
            gov_bonds_held=0, interbank_claims=0,
            deposits_from_hh=1100, deposits_from_firms=0,
            interbank_debt=0, bonds_issued=0,
            capital=0,
        )
        assert bs.net_worth == 0


# ════════════════════════════════════════════════════════════
# GovernmentBalanceSheet
# ════════════════════════════════════════════════════════════
class TestGovernmentBalanceSheet:
    """政府 BS: 通常 NW 为负（债务 > 资产）。"""

    def test_zero_state(self):
        bs = GovernmentBalanceSheet()
        assert bs.sum_assets() == 0
        assert bs.sum_liabilities() == 0
        assert bs.net_worth == 0

    def test_typical_government_has_negative_nw(self):
        bs = GovernmentBalanceSheet(
            treasury_deposits=500, other_assets=200,
            bonds_outstanding=10000,
        )
        # A = 700, L = 10000, NW = -9300
        assert bs.sum_assets() == 700
        assert bs.sum_liabilities() == 10000
        assert bs.net_worth == -9300

    def test_surplus_government_has_positive_nw(self):
        bs = GovernmentBalanceSheet(
            treasury_deposits=2000, other_assets=500,
            bonds_outstanding=1000,
        )
        assert bs.net_worth == 1500


# ════════════════════════════════════════════════════════════
# CentralBankBalanceSheet
# ════════════════════════════════════════════════════════════
class TestCentralBankBalanceSheet:
    """CB BS: 资本独立. NW = capital 字段.

    不变量: sum_assets() == sum_liabilities() + capital
    """

    def test_zero_state(self):
        bs = CentralBankBalanceSheet()
        assert bs.sum_assets() == 0
        assert bs.sum_liabilities() == 0
        assert bs.net_worth == 0

    def test_typical_cb_with_balanced_invariant(self):
        bs = CentralBankBalanceSheet(
            gov_bonds=5000, lolr_claims=500, other_assets=200,
            bank_reserves=4500, currency_issued=1000,
            capital=200,
        )
        # A = 5700, L = 5500, A - L = 200 = capital
        assert bs.sum_assets() == 5700
        assert bs.sum_liabilities() == 5500
        assert bs.net_worth == 200


# ════════════════════════════════════════════════════════════
# 跨类不变量
# ════════════════════════════════════════════════════════════
class TestCrossSectorInvariants:
    """检验一个完整经济的资产 = 负债 + 净值 恒等式."""

    def test_full_economy_balance_sheet_identity(self):
        """构造一个虚拟均衡: 部门间债权债务互相抵消."""
        # 家庭: 资产包括银行存款 (银行的负债)
        hh = HouseholdBalanceSheet(
            deposits=8000, housing_self=10000, cash=2000,
            mortgage=20000,
        )
        # 企业: 资产包括银行存款 + 资本
        f = FirmBalanceSheet(
            deposits=1500, capital_stock=20000, inventories=5000,
            bank_loans=10000, accounts_payable=2000,
        )
        # 银行: 资本 + 负债 = 资产
        b = CommercialBankBalanceSheet(
            reserves=1000, loans_to_firms=10000, loans_to_households=20000,
            deposits_from_hh=8000, deposits_from_firms=1500,
            capital=21500,
        )
        # 政府: 发行国债
        g = GovernmentBalanceSheet(
            bonds_outstanding=15000,
        )
        # CB: 持有政府债 + 银行准备金
        cb = CentralBankBalanceSheet(
            gov_bonds=15000,
            bank_reserves=1000,
            capital=14000,
        )

        # 家庭 NW = 20000 - 20000 = 0
        assert hh.net_worth == 0
        # 企业 NW = 26500 - 12000 = 14500
        assert f.net_worth == 14500
        # 银行 NW = 21500
        assert b.net_worth == 21500
        # 政府 NW = -15000
        assert g.net_worth == -15000
        # CB NW = 14000
        assert cb.net_worth == 14000

        # 加和: 全经济 NW = 0 + 14500 + 21500 - 15000 + 14000 = 35000
        total_nw = hh.net_worth + f.net_worth + b.net_worth + g.net_worth + cb.net_worth
        assert total_nw == 35000
