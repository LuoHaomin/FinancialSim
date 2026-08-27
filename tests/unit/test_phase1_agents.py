"""Phase 1 主体扩展测试: 财富效应 / 折旧投资 / 银行利润循环."""
from __future__ import annotations

from financial_sim.agents.commercial_bank import CommercialBank
from financial_sim.agents.firm import Firm
from financial_sim.agents.household import Household


class TestHouseholdPermanentIncome:
    def test_consumption_uses_permanent_income(self):
        h = Household(id="h", mpc=0.5, income=10.0)
        h.permanent_income = 4.0
        assert h.decide_consumption() == 2.0  # 用永久收入而非当期收入

    def test_permanent_income_converges(self):
        h = Household(id="h", income=1.0, income_adapt_speed=0.5)
        h.permanent_income = 0.0
        for _ in range(50):
            h.update_permanent_income()
        assert abs(h.permanent_income - 1.0) < 1e-6

    def test_first_update_seeds_from_income(self):
        h = Household(id="h", income=3.0)
        h.update_permanent_income()
        assert h.permanent_income == 3.0


class TestHouseholdWealthEffect:
    def test_zero_lambda_matches_linear(self):
        h = Household(id="h", deposits=1000.0, mpc=0.7, income=1.0)
        h.wealth_effect_coef = 0.0
        assert abs(h.decide_consumption() - 0.7) < 1e-12

    def test_positive_lambda_pulls_consumption_up(self):
        h = Household(id="h", deposits=10000.0, mpc=0.7, income=1.0)
        h.permanent_income = 1.0
        h.wealth_effect_coef = 0.05
        # buffer = 3×pi = 3; excess = 10000+cash − 3
        expected = 0.7 + 0.05 * (10000.0 - 3.0)
        assert abs(h.decide_consumption() - expected) < 1e-9

    def test_no_negative_consumption(self):
        h = Household(id="h", deposits=-5.0, mpc=0.7)
        h.wealth_effect_coef = 0.1
        assert h.decide_consumption() >= 0.0


class TestFirmCapital:
    def test_depreciation(self):
        f = Firm(id="f", sector="s", capital=200.0, depreciation_rate=0.01)
        f.depreciate()
        assert abs(f.capital - 198.0) < 1e-9

    def test_investment_capped_by_deposits(self):
        f = Firm(id="f", sector="s", capital=10.0, deposits=30.0,
                 investment_sensitivity=0.5,
                 employees=20, capital_per_worker_target=10.0)
        want = f.decide_investment()
        assert want == min(0.5 * (200 - 10), 30.0)

    def test_invest_increases_capital(self):
        f = Firm(id="f", sector="s", capital=10.0, deposits=100.0)
        f.invest(40.0)
        assert f.capital == 50.0
        # SFC 注记: 聚合设定下投资不改存款 (见 invest docstring)
        assert f.deposits == 100.0

    def test_calvo_reprice_sets_markup_price(self):
        f = Firm(id="f", sector="s", price=1.0, wage_offered=2.0,
                 productivity=1.0, calvo_price_prob=1.0, calvo_markup_target=0.10)
        assert f.maybe_calvo_reprice(0.5) is True
        assert abs(f.price - 2.2) < 1e-9

    def test_calvo_no_reprice_when_not_drawn(self):
        f = Firm(id="f", sector="s", price=1.0, wage_offered=2.0,
                 productivity=1.0, calvo_price_prob=0.3)
        assert f.maybe_calvo_reprice(0.5) is False
        assert f.price == 1.0


def _bank(reserves=100.0, loans=500.0, dep_hh=600.0, cap=0.0) -> CommercialBank:
    return CommercialBank(
        reserves=reserves, loans_to_firms=loans,
        deposits_from_hh=dep_hh, capital=cap,
    )


class TestBankRates:
    def test_rates_basic(self):
        b = _bank()
        loan, dep = b.set_rates(policy_rate=0.03)
        assert abs(loan - (0.03 + b.loan_rate_base_spread
                           + b.loan_rate_car_pressure * b.car_gap())) < 1e-12
        assert abs(dep - 0.01) < 1e-12

    def test_loan_spread_rises_when_car_low(self):
        under = CommercialBank(
            reserves=100.0, loans_to_firms=900.0,
            deposits_from_hh=1000.0, capital=0.0,
            car_requirement=0.08, car_buffer=0.02,
        )
        normal, _ = under.set_rates(0.03)
        under.capital = -300.0  # CAR 深度为负
        stressed, _ = under.set_rates(0.03)
        assert stressed > normal

    def test_deposit_rate_floored(self):
        b = _bank()
        _, dep = b.set_rates(policy_rate=0.001, rate_floor=-0.005)
        assert dep == -0.005


class TestBankProfit:
    def test_income_and_expense_flow_to_capital(self):
        b = _bank(cap=100.0)
        b.book_loan_interest_income(7.0)
        b.book_deposit_interest_expense(3.0)
        assert abs(b.capital - 104.0) < 1e-12

    def test_car_gap_bounded_at_zero(self):
        b = _bank(cap=500.0)
        assert b.car_gap() == 0.0
