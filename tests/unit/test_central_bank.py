"""Tests for CentralBank (Phase 0 simplified)."""
from __future__ import annotations

from financial_sim.agents.central_bank import CentralBank


class TestCentralBankBasics:
    def test_initial_state(self):
        cb = CentralBank()
        assert cb.policy_rate == 0.025  # 2.5% 默认
        assert cb.target_inflation == 0.02
        assert cb.neutral_rate == 0.02


class TestTaylorRule:
    def test_at_target_no_change(self):
        """通胀 = 目标, 产出缺口 = 0, 利率应 = 中性利率."""
        cb = CentralBank(policy_rate=0.025)
        new_rate = cb.taylor_rule(inflation=0.02, output_gap=0.0, smoothing=0.0)
        # r_target = 0.02 + 1.5*0 + 0.5*0 = 0.02
        # r_new = 0 * 0.025 + 1.0 * 0.02 = 0.02
        assert abs(new_rate - 0.02) < 1e-9

    def test_high_inflation_raises_rate(self):
        cb = CentralBank(policy_rate=0.025)
        new_rate = cb.taylor_rule(inflation=0.04, output_gap=0.0, smoothing=0.0)
        # r_target = 0.02 + 1.5*0.02 + 0 = 0.05
        assert abs(new_rate - 0.05) < 1e-9

    def test_negative_output_gap_lowers_rate(self):
        cb = CentralBank(policy_rate=0.025)
        new_rate = cb.taylor_rule(inflation=0.02, output_gap=-0.02, smoothing=0.0)
        # r_target = 0.02 + 0 + 0.5*(-0.02) = 0.01
        assert abs(new_rate - 0.01) < 1e-9

    def test_zero_lower_bound(self):
        """极端情况下不应低于 -0.5%."""
        cb = CentralBank(policy_rate=0.025)
        new_rate = cb.taylor_rule(inflation=-0.05, output_gap=-0.10, smoothing=0.0)
        assert new_rate >= -0.005

    def test_smoothing_smooths_transitions(self):
        """惯性 Taylor: 渐进调整."""
        cb = CentralBank(policy_rate=0.025)
        # r_target = 0.05 (高通胀)
        # r_new = 0.85 * 0.025 + 0.15 * 0.05 = 0.02125 + 0.0075 = 0.02875
        new_rate = cb.taylor_rule(inflation=0.04, output_gap=0.0, smoothing=0.85)
        expected = 0.85 * 0.025 + 0.15 * 0.05
        assert abs(new_rate - expected) < 1e-9


class TestCentralBankBalanceSheet:
    def test_initial_balance_sheet(self):
        cb = CentralBank()
        assert cb.gov_bonds == 0
        assert cb.bank_reserves == 0
        assert cb.currency_issued == 0
        assert cb.capital == 0

    def test_omo_buy_injects_reserves(self):
        """OMO 买入国债 → 银行准备金增加."""
        cb = CentralBank()
        cb.omo_buy(amount=1000)
        assert cb.gov_bonds == 1000
        assert cb.bank_reserves == 1000
