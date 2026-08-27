"""Tests for CommercialBank (Phase 0 simplified)."""
from __future__ import annotations

from financial_sim.agents.commercial_bank import CommercialBank


class TestBankBasics:
    def test_initial_state(self):
        b = CommercialBank(id="bank_1", capital=100)
        assert b.id == "bank_1"
        assert b.capital == 100
        assert b.deposits_from_hh == 0

    def test_total_assets(self):
        b = CommercialBank(
            id="bank_1",
            reserves=100, loans_to_firms=500, loans_to_households=300,
            gov_bonds_held=50,
        )
        assert b.total_assets() == 950

    def test_total_liabilities(self):
        b = CommercialBank(
            id="bank_1",
            deposits_from_hh=800, deposits_from_firms=200,
        )
        assert b.total_liabilities() == 1000


class TestBankCAR:
    def test_car_with_balanced_state(self):
        """A=950, L=1000, capital=100 → A = L - capital? 不对.
        bank.A = reserves + loans + bonds
        bank.L = deposits + ...
        bank.A - bank.L = capital (不变量)
        这里 A = 950, L = 1000, capital = -50? 但 CAR 总是正的.
        """
        # 重新设置: A = 1050, L = 950, capital = 100
        b = CommercialBank(
            id="bank_1",
            reserves=100, loans_to_firms=500, loans_to_households=300,
            gov_bonds_held=150,  # 总 = 1050
            deposits_from_hh=800, deposits_from_firms=150,  # 总 = 950
            capital=100,
        )
        assert b.total_assets() - b.total_liabilities() == b.capital
        assert b.car() == 100 / 1050  # ≈ 0.095

    def test_car_zero_assets_infinite(self):
        """没有资产时, CAR 无定义 (返回无穷大)."""
        b = CommercialBank(id="bank_1")
        assert b.car() == float("inf")
