"""Tests for Household agent (Phase 0 simplified)."""
from __future__ import annotations

from financial_sim.agents.household import Household


class TestHouseholdBasics:
    """基本状态与字段."""

    def test_initial_state(self):
        h = Household(id="h1", sector="consumer_goods", wage=1000)
        assert h.id == "h1"
        assert h.sector == "consumer_goods"
        assert h.wage == 1000
        assert h.employed is True

    def test_default_values(self):
        h = Household(id="h1", sector="consumer_goods")
        assert h.cash == 0.0
        assert h.deposits == 0.0
        assert h.income == 0.0
        assert h.unemployment_duration == 0

    def test_net_worth_no_debt(self):
        """Phase 0 无负债, NW = 现金 + 存款."""
        h = Household(id="h1", sector="consumer_goods", cash=500, deposits=2000)
        assert h.net_worth() == 2500


class TestHouseholdConsumptionSavings:
    """消费与储蓄决策 (Phase 0: 线性)."""

    def test_consumption_proportional_to_income(self):
        h = Household(id="h1", sector="consumer_goods")
        h.income = 1000
        c = h.decide_consumption()
        assert c == 700  # mpc=0.7, savings_rate=0.3 (默认值)

    def test_savings_complements_consumption(self):
        h = Household(id="h1", sector="consumer_goods")
        h.income = 1000
        c = h.decide_consumption()
        s = h.decide_savings()
        assert c + s == h.income

    def test_zero_income_zero_consumption(self):
        h = Household(id="h1", sector="consumer_goods", employed=False)
        h.income = 0
        assert h.decide_consumption() == 0
        assert h.decide_savings() == 0


class TestHouseholdLabor:
    """就业状态管理."""

    def test_initial_employment(self):
        h = Household(id="h1", sector="consumer_goods")
        assert h.employed is True

    def test_lose_job(self):
        h = Household(id="h1", sector="consumer_goods", employed=True)
        h.lose_job()
        assert h.employed is False
        assert h.unemployment_duration == 0

    def test_unemployment_duration_increments(self):
        h = Household(id="h1", sector="consumer_goods", employed=False)
        h.unemployment_duration = 3
        h.tick_unemployment()
        assert h.unemployment_duration == 4

    def test_find_job_resets_unemployment(self):
        h = Household(id="h1", sector="consumer_goods", employed=False)
        h.unemployment_duration = 5
        h.find_job(sector="consumer_goods", wage=1500)
        assert h.employed is True
        assert h.unemployment_duration == 0
        assert h.wage == 1500
        assert h.sector == "consumer_goods"
