"""Tests for GoodsMarket (Phase 0 simplified)."""
from __future__ import annotations

from financial_sim.config import SimConfig
from financial_sim.core import Simulation
from financial_sim.markets.goods import GoodsMarket


def _set_household_incomes(sim, wage: float = 1.0) -> None:
    """辅助: 给所有家庭设置收入与永久收入, 关闭财富效应.

    这样 decide_consumption() = mpc * wage 精确可控.
    """
    for h in sim.state.households:
        h.income = wage
        h.permanent_income = wage
        h.wealth_effect_coef = 0.0
        h.mpc = 0.7


def _set_firm_sales(sim, sales: float = 7.0) -> None:
    """辅助: 写入上月实际销售额 (Phase 3 逐企业定价基准).

    10 户 × mpc 0.7 × 工资 1 = 7.
    """
    for f in sim.state.firms:
        f.last_sales = sales


class TestGoodsMarketInventory:
    """库存-价格反馈."""

    def test_high_inventory_lowers_price(self):
        """库存 > 1.5 倍目标 → 降价 5%."""
        sim = Simulation(SimConfig(n_households=10, n_ticks=1))
        _set_household_incomes(sim)
        _set_firm_sales(sim)
        firm = sim.state.firm
        assert firm is not None

        firm.inventory = 100.0
        initial_price = firm.price

        market = GoodsMarket()
        market.clear(sim.state)

        assert firm.price < initial_price

    def test_low_inventory_raises_price(self):
        """库存 < 0.5 倍目标 → 提价 5%."""
        sim = Simulation(SimConfig(n_households=10, n_ticks=1))
        _set_household_incomes(sim)
        _set_firm_sales(sim)
        firm = sim.state.firm
        assert firm is not None

        firm.inventory = 0.1
        initial_price = firm.price

        market = GoodsMarket()
        market.clear(sim.state)

        assert firm.price > initial_price

    def test_normal_inventory_keeps_price(self):
        """库存正常 → 价格不变."""
        sim = Simulation(SimConfig(n_households=10, n_ticks=1))
        _set_household_incomes(sim)
        _set_firm_sales(sim)
        firm = sim.state.firm
        assert firm is not None

        firm.inventory = 7.0
        initial_price = firm.price

        market = GoodsMarket()
        market.clear(sim.state)

        assert abs(firm.price - initial_price) < 1e-9


class TestGoodsMarketInventoryUpdate:
    """库存更新: 期末 = 期初 + 生产 - 销量."""

    def test_inventory_update(self):
        sim = Simulation(SimConfig(n_households=10, n_ticks=1))
        _set_household_incomes(sim)
        _set_firm_sales(sim)   # 销量 = 7
        firm = sim.state.firm
        assert firm is not None

        firm.inventory = 5.0
        firm.productivity = 2.0
        firm.employees = 10  # 生产 = 20

        market = GoodsMarket()
        market.update_inventory(sim.state)

        # 期末 = 5 + 20 - 7 = 18
        assert abs(firm.inventory - 18.0) < 1e-9

    def test_inventory_cannot_go_negative(self):
        """库存不能为负 (强制下限 0)."""
        sim = Simulation(SimConfig(n_households=10, n_ticks=1))
        _set_household_incomes(sim)
        _set_firm_sales(sim)   # 销量 = 7
        firm = sim.state.firm
        assert firm is not None

        firm.inventory = 1.0
        firm.productivity = 1.0
        firm.employees = 1  # 生产 = 1

        market = GoodsMarket()
        market.update_inventory(sim.state)

        # 期末 = 1 + 1 - 7 = -5 → 应被钳到 0
        assert firm.inventory == 0.0
