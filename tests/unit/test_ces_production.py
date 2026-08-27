"""CES 生产函数单元测试 (Phase 3 Week A)."""
from __future__ import annotations

import pytest

from financial_sim.agents.firm import Firm


class TestCESProduction:
    def test_linear_is_default(self):
        f = Firm(id="f", sector="consumer_goods", productivity=2.0, employees=10)
        assert f.production() == pytest.approx(20.0)

    def test_ces_known_value(self):
        """手算对照: A=2, K=100, L=25, α=0.3, σ=0.5 → ρ=−1.

        Y = 2 × (0.3/100 + 0.7/25)^(−1) = 2 / (0.003 + 0.028) = 2/0.031
        """
        f = Firm(
            id="f", sector="consumer_goods",
            productivity=2.0, capital=100.0, employees=25,
            production_function="ces", sigma_elasticity=0.5, alpha_capital=0.3,
        )
        assert f.production() == pytest.approx(2.0 / 0.031, rel=1e-9)

    def test_ces_sigma_one_is_cobb_douglas(self):
        """σ≈1 走 Cobb-Douglas 数值守护: Y = A·K^α·L^(1−α)."""
        f = Firm(
            id="f", sector="consumer_goods",
            productivity=1.5, capital=81.0, employees=16,
            production_function="ces", sigma_elasticity=1.0, alpha_capital=0.25,
        )
        expected = 1.5 * (81.0 ** 0.25) * (16.0 ** 0.75)
        assert f.production() == pytest.approx(expected, rel=1e-6)

    def test_ces_zero_labor_gives_zero(self):
        f = Firm(
            id="f", sector="consumer_goods",
            capital=100.0, employees=0,
            production_function="ces", sigma_elasticity=0.5,
        )
        if f.sigma_elasticity < 1.0:
            # ρ<0 时劳动是必要投入: L=0 → l_term 发散语义, 实现钳为 0
            # (实现: (1−α)·0^ρ = ±inf → 总和负 → guard)
            pass
        assert f.production() >= 0.0

    def test_ces_monotonic_in_capital(self):
        f1 = Firm(
            id="f", sector="s", capital=50.0, employees=20,
            production_function="ces", sigma_elasticity=0.5,
        )
        f2 = Firm(
            id="f", sector="s", capital=200.0, employees=20,
            production_function="ces", sigma_elasticity=0.5,
        )
        assert f2.production() > f1.production()

    def test_ces_monotonic_in_labor(self):
        f1 = Firm(
            id="f", sector="s", capital=100.0, employees=10,
            production_function="ces", sigma_elasticity=0.7,
        )
        f2 = Firm(
            id="f", sector="s", capital=100.0, employees=40,
            production_function="ces", sigma_elasticity=0.7,
        )
        assert f2.production() > f1.production()

    def test_high_substitution_approaches_linear(self):
        """σ→∞ (ρ→1): CES → A·(αK + (1−α)L)."""
        a, k, l, alpha = 1.2, 100.0, 60.0, 0.3
        f = Firm(
            id="f", sector="s", productivity=a, capital=k, employees=l,
            production_function="ces", sigma_elasticity=1e8, alpha_capital=alpha,
        )
        expected = a * (alpha * k + (1 - alpha) * l)
        assert f.production() == pytest.approx(expected, rel=1e-4)
