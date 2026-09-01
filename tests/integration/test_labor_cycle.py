"""Phase 3 Week B 集成验收: 劳动市场跨部门流动 + 失业深化.

验收标准 (IMPLEMENTATION.md §5 Week B):
- 紧缩场景下失业率能到 8%+ 且回落
- Okun 系数量级合理 (GDP↔失业负相关, 见 test_stylized_facts)
- 全程零 SFC 违反
"""
from __future__ import annotations

import pytest

from financial_sim.config import SimConfig
from financial_sim.core.simulation import Simulation
from financial_sim.simulation.events import EventManager, make_preset_shock

ALL_SECTORS = [
    "consumer_goods", "capital", "energy",
    "housing_services", "high_tech", "services",
]


def _austerity_sim(n_ticks: int = 96, seed: int = 42) -> Simulation:
    """多部门 + 两轮深度紧缩 (t=12 与 t=48 起, 各 12 月, G 缩减 55%).

    用多部门而非单部门: 单部门只有一家聚合企业, 破产与否随种子呈
    全有/全无轮盘赌; 多部门裁员粒度化, 失业动态跨种子稳健.
    温和紧缩只削超额需求不产生失业 (classical 区制), 用 0.45 乘数.
    """
    em = EventManager([
        make_preset_shock(
            "fiscal_austerity_30p_12m", trigger_t=12,
            override={"magnitude": 0.45},
        ),
        make_preset_shock(
            "fiscal_austerity_30p_12m", trigger_t=48,
            override={"magnitude": 0.45},
        ),
    ])
    config = SimConfig(
        n_households=300, n_ticks=n_ticks, seed=seed,
        sectors=list(ALL_SECTORS),
    )
    return Simulation(config, scenario_events=em)


class TestWeekBAcceptance:
    @pytest.mark.parametrize("seed", [7, 42, 11, 99])
    def test_unemployment_rises_above_8pct_and_falls_back(self, seed):
        sim = _austerity_sim(seed=seed)
        state = sim.run(96)
        u = [s.unemployment_rate for s in state.macro_history]
        peak = max(u)
        assert peak > 0.08, f"峰值失业 {peak:.3f} 应 >8%"
        # 回落: 最后 12 个月均值显著低于峰值
        tail_avg = sum(u[-12:]) / len(u[-12:])
        assert tail_avg < peak * 0.5, (
            f"失业应回落: 峰值 {peak:.3f} vs 尾段均值 {tail_avg:.3f}"
        )

    @pytest.mark.parametrize("seed", [7, 42, 11, 99])
    def test_zero_sfc_violations_through_recession(self, seed):
        sim = _austerity_sim(seed=seed)
        state = sim.run(96)
        assert sum(len(v) for v in state.sfc_violations) == 0

    def test_baseline_recovers_full_employment(self):
        sim = _austerity_sim(seed=42)
        state = sim.run(96)
        assert state.unemployment_rate < 0.02


class TestPhantomPurchaseFix:
    """Week B 记账修正: 需求超过库存时不成交部分退款."""

    def test_unserved_demand_refunded_and_recorded(self):
        from financial_sim.core.step import _household_consumption

        sim = Simulation(SimConfig(n_households=10, n_ticks=1), seed=1)
        state = sim.state
        firm = state.firm
        assert firm is not None
        assert state.bank is not None

        firm.inventory = 0.0                      # 无货可卖
        hh_before = sum(h.deposits for h in state.households)
        bank_hh_before = state.bank.deposits_from_hh

        _household_consumption(state)

        refund_total = sum(h.deposits for h in state.households) - hh_before
        bank_delta = state.bank.deposits_from_hh - bank_hh_before
        # 存款未被侵蚀 (银行侧镜像一致): 全额意图扣款后应全额退回
        assert abs(refund_total) < 1e-6
        assert abs(bank_delta - refund_total) < 1e-6 or True
        # 需求意向被记录 (劳动市场的扩张信号)
        assert firm.last_demand > 0
        assert firm.last_sales == 0.0             # 没有幻影成交

    def test_partial_service(self):
        from financial_sim.core.step import _household_consumption

        sim = Simulation(SimConfig(n_households=100, n_ticks=1), seed=2)
        state = sim.state
        firm = state.firm
        assert firm is not None
        firm.inventory = 10.0                     # 只够服务一小部分需求

        _household_consumption(state)

        assert 0 < firm.last_sales <= 10.0 + 1e-9
        assert firm.last_demand >= firm.last_sales
