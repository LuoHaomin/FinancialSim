"""Tests for Government (Phase 0 simplified)."""
from __future__ import annotations

from financial_sim.agents.government import Government


class TestGovernmentBasics:
    def test_initial_state(self):
        g = Government()
        assert g.debt == 0
        assert g.tax_revenue == 0
        assert g.gov_spending > 0  # 默认有支出
        assert g.transfers > 0     # 默认有转移支付

    def test_interest_payment(self):
        g = Government(debt=1000, interest_rate=0.025)
        assert g.compute_interest() == 25


class TestGovernmentTax:
    def test_collect_income_tax(self):
        g = Government()
        tax = g.collect_taxes(total_income=10000, total_profit=0)
        # 默认所得税率 25%
        assert tax == 2500

    def test_collect_corporate_tax(self):
        g = Government()
        tax = g.collect_taxes(total_income=0, total_profit=10000)
        # 默认公司税率 21%
        assert tax == 2100

    def test_collect_both_taxes(self):
        g = Government()
        tax = g.collect_taxes(total_income=10000, total_profit=10000)
        # 2500 + 2100 = 4600
        assert tax == 4600

    def test_loss_no_corporate_tax(self):
        """公司亏损不收税."""
        g = Government()
        tax = g.collect_taxes(total_income=0, total_profit=-1000)
        assert tax == 0


class TestGovernmentBudget:
    def test_primary_balance(self):
        g = Government(tax_revenue=1000, gov_spending=800, transfers=100)
        # primary = 1000 - 800 - 100 = 100
        assert g.primary_balance() == 100

    def test_deficit_increases_debt(self):
        g = Government(debt=1000)
        # 支出 > 税收 → 赤字 → 发行新债
        g.issue_debt_to_balance(
            gov_spending=500, transfers=100,
            tax_revenue=400, interest_payment=50,
        )
        # deficit = 500 + 100 + 50 - 400 = 250
        assert g.debt == 1250

    def test_surplus_decreases_debt(self):
        g = Government(debt=1000)
        g.issue_debt_to_balance(
            gov_spending=400, transfers=100,
            tax_revenue=600, interest_payment=50,
        )
        # deficit = 400 + 100 + 50 - 600 = -50
        assert g.debt == 950
