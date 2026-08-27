"""Tests for Firm agent (Phase 0 simplified)."""
from __future__ import annotations

from financial_sim.agents.firm import Firm


class TestFirmBasics:
    def test_initial_state(self):
        f = Firm(id="f1", sector="consumer_goods")
        assert f.id == "f1"
        assert f.sector == "consumer_goods"
        assert f.employees == 0

    def test_default_capital(self):
        f = Firm(id="f1", sector="consumer_goods")
        assert f.capital == 100.0
        assert f.debt == 0.0


class TestFirmProduction:
    def test_production_zero_employees(self):
        f = Firm(id="f1", sector="consumer_goods", productivity=2.0, employees=0)
        assert f.production() == 0

    def test_production_proportional_to_workers(self):
        f = Firm(id="f1", sector="consumer_goods", productivity=2.0, employees=10)
        assert f.production() == 20

    def test_revenue(self):
        f = Firm(id="f1", sector="consumer_goods", productivity=2.0,
                 employees=10, price=5.0)
        assert f.revenue() == 100  # 20 * 5

    def test_labor_cost(self):
        f = Firm(id="f1", sector="consumer_goods", employees=10, wage_offered=100)
        assert f.labor_cost() == 1000


class TestFirmProfitAndSelling:
    def test_profit(self):
        f = Firm(id="f1", sector="consumer_goods", productivity=2.0,
                 employees=10, price=5.0, wage_offered=50)
        # revenue = 100, cost = 500, profit = -400
        assert f.profit() == -400

    def test_sell_adds_to_deposits(self):
        f = Firm(id="f1", sector="consumer_goods", price=10.0, deposits=100)
        revenue = f.sell(5)
        assert revenue == 50
        assert f.deposits == 150

    def test_sell_zero_quantity(self):
        f = Firm(id="f1", sector="consumer_goods", price=10.0, deposits=100)
        revenue = f.sell(0)
        assert revenue == 0
        assert f.deposits == 100


class TestFirmHiring:
    def test_hire_increases_employees(self):
        f = Firm(id="f1", sector="consumer_goods", employees=10)
        f.hire(5)
        assert f.employees == 15

    def test_fire_decreases_employees(self):
        f = Firm(id="f1", sector="consumer_goods", employees=10)
        f.fire(3)
        assert f.employees == 7

    def test_fire_cannot_go_negative(self):
        f = Firm(id="f1", sector="consumer_goods", employees=2)
        f.fire(5)
        assert f.employees == 0
