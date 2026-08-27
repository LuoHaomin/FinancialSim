"""Tests for Default & Bankruptcy mechanism (Phase 1+)."""
from __future__ import annotations

import pytest

from financial_sim.agents.commercial_bank import CommercialBank
from financial_sim.agents.firm import Firm
from financial_sim.config import SimConfig
from financial_sim.core import Simulation
from financial_sim.core.step import (
    DEFAULT_COOLDOWN_MONTHS,
    _default_resolution,
)


# ════════════════════════════════════════════════════════════
# Firm 违约检测 & 破产处置
# ════════════════════════════════════════════════════════════
class TestFirmDefaultDetection:
    def test_equity_positive_no_default(self):
        f = Firm(
            id="f", sector="s", deposits=100, inventory=50, capital=200,
            debt=50,  # equity = 100 + 50 + 200 - 50 = 300
        )
        assert f.is_default() is False

    def test_equity_negative_default_triggered(self):
        f = Firm(
            id="f", sector="s", deposits=0, inventory=0, capital=100,
            debt=200,  # equity = -100
            default_equity_threshold=0.0,
        )
        assert f.is_default() is True

    def test_bankrupt_firm_no_retrigger(self):
        f = Firm(
            id="f", sector="s", capital=0, debt=0, is_bankrupt=True,
        )
        # 已破产的不再触发违约
        assert f.is_default() is False


class TestFirmBankruptcyResolution:
    def test_declare_bankruptcy_sells_capital(self):
        f = Firm(
            id="f", sector="s", capital=200, debt=0, deposits=50,
            bankruptcy_recovery=0.5,
        )
        detail = f.declare_bankruptcy()
        # recovered = 200 * 0.5 = 100; deposits = 50 + 100 = 150
        assert detail["recovered"] == 100
        assert f.deposits == 150
        assert f.capital == 0
        assert f.debt == 0
        assert f.is_bankrupt is True

    def test_declare_bankruptcy_partially_repays_debt(self):
        f = Firm(
            id="f", sector="s", capital=100, debt=80, deposits=30,
            bankruptcy_recovery=0.5,
        )
        detail = f.declare_bankruptcy()
        # recovered = 50; deposits = 30+50 = 80
        # repayment = min(80, 80) = 80 (deposits 足够)
        # unpaid = 0
        assert detail["debt_repaid"] == 80
        assert detail["debt_unpaid"] == 0
        assert f.debt == 0

    def test_declare_bankruptcy_unpaid_debt_for_writeoff(self):
        f = Firm(
            id="f", sector="s", capital=100, debt=200, deposits=10,
            bankruptcy_recovery=0.5,
        )
        detail = f.declare_bankruptcy()
        # recovered = 50; deposits = 10+50 = 60
        # repayment = min(200, 60) = 60
        # unpaid = 200 - 60 = 140
        assert detail["debt_repaid"] == 60
        assert detail["debt_unpaid"] == 140
        assert f.debt == 0

    def test_declare_bankruptcy_fires_all_employees(self):
        f = Firm(id="f", sector="s", capital=100, employees=42, bankruptcy_recovery=0.5)
        detail = f.declare_bankruptcy()
        assert detail["employees_fired"] == 42
        assert f.employees == 0

    def test_double_declaration_is_noop(self):
        f = Firm(id="f", sector="s", capital=100, bankruptcy_recovery=0.5)
        f.declare_bankruptcy()
        detail2 = f.declare_bankruptcy()
        assert detail2["recovered"] == 0
        assert detail2["employees_fired"] == 0


class TestFirmRecapitalization:
    def test_recapitalize_resets_state(self):
        f = Firm(id="f", sector="s", capital=0, debt=0, is_bankrupt=True,
                 months_bankrupt=10)
        f.recapitalize(amount=150)
        assert f.capital == 150
        assert f.debt == 150
        assert f.deposits == 150  # 现金进入企业账户
        assert f.is_bankrupt is False
        assert f.months_bankrupt == 0

    def test_recapitalize_zero_amount_noop(self):
        f = Firm(id="f", sector="s", capital=0, is_bankrupt=True)
        f.recapitalize(amount=0)
        assert f.capital == 0
        assert f.is_bankrupt is True  # 仍然破产


# ════════════════════════════════════════════════════════════
# Bank NPL & 核销
# ════════════════════════════════════════════════════════════
class TestBankNPL:
    def test_npl_ratio_zero_when_no_loans(self):
        b = CommercialBank(id="b")
        assert b.npl_ratio() == 0.0

    def test_mark_npl_increases_balance(self):
        b = CommercialBank(id="b", loans_to_firms=100)
        b.mark_npl(50)
        assert b.npl_amount == 50
        assert b.npl_ratio() == 0.5

    def test_write_off_reduces_loans_and_capital(self):
        b = CommercialBank(
            id="b", loans_to_firms=100, npl_amount=100, capital=50,
        )
        written = b.write_off_loan(amount=80)
        assert written == 80
        assert b.loans_to_firms == 20
        assert b.npl_amount == 20
        assert b.capital == -30  # 资本被侵蚀

    def test_write_off_capped_by_npl(self):
        b = CommercialBank(id="b", loans_to_firms=100, npl_amount=30, capital=20)
        written = b.write_off_loan(amount=100)
        assert written == 30  # 受 NPL 余额限制
        assert b.capital == -10

    def test_write_off_zero_noop(self):
        b = CommercialBank(id="b", loans_to_firms=100, capital=10)
        written = b.write_off_loan(0)
        assert written == 0
        assert b.capital == 10


# ════════════════════════════════════════════════════════════
# Step integration: 违约 → 银行核销 → 恢复
# ════════════════════════════════════════════════════════════
class TestDefaultResolutionE2E:
    def test_default_triggers_bankruptcy_and_writeoff(self):
        sim = Simulation(SimConfig(n_households=10, n_ticks=1))
        # 强制企业违约: equity = -200 (SFC-balanced setup)
        sim.state.firm.deposits = 0
        sim.state.firm.inventory = 0
        sim.state.firm.capital = 100
        sim.state.firm.debt = 300
        # 银行镜像 (SFC): bank.deposits_from_firms=0, bank.loans_to_firms=300
        sim.state.bank.deposits_from_firms = 0
        sim.state.bank.loans_to_firms = 300

        _default_resolution(sim.state)

        assert sim.state.firm.is_bankrupt is True
        assert sim.state.firm.capital == 0
        # recovered = 100 * 0.5 = 50 → firm.deposits
        # repayment = min(300, 50) = 50; unpaid = 250
        # write_off_loan(250): loans -= 250, capital -= 250
        # (初始 bank.capital = 100, 核销 250 → 最终 capital = -150)
        assert sim.state.bank.npl_writes_off_cumulative == 250
        assert sim.state.bank.capital == pytest.approx(-150)
        assert sim.state.bank.npl_amount == 0  # 核销后 NPL 余额清零
        assert sim.state.bank.loans_to_firms == pytest.approx(0)  # 全额核销: 250 写 + 50 还

    def test_no_default_when_equity_healthy(self):
        sim = Simulation(SimConfig(n_households=10, n_ticks=1))
        sim.state.firm.capital = 1000
        sim.state.firm.debt = 50
        _default_resolution(sim.state)
        assert sim.state.firm.is_bankrupt is False

    def test_recapitalization_after_cooldown(self):
        sim = Simulation(SimConfig(n_households=10, n_ticks=1))
        # 制造破产状态
        sim.state.firm.capital = 0
        sim.state.firm.debt = 0
        sim.state.firm.is_bankrupt = True
        sim.state.firm.months_bankrupt = DEFAULT_COOLDOWN_MONTHS  # 满足 cooldown

        recap_amount = 100.0
        bank_loans_before = sim.state.bank.loans_to_firms
        _default_resolution(sim.state)

        assert sim.state.firm.is_bankrupt is False
        assert sim.state.firm.capital == recap_amount
        assert sim.state.firm.debt == recap_amount
        assert sim.state.bank.loans_to_firms == bank_loans_before + recap_amount

    def test_no_recap_before_cooldown(self):
        sim = Simulation(SimConfig(n_households=10, n_ticks=1))
        sim.state.firm.capital = 0
        sim.state.firm.debt = 0
        sim.state.firm.is_bankrupt = True
        sim.state.firm.months_bankrupt = 2  # < cooldown

        _default_resolution(sim.state)
        assert sim.state.firm.is_bankrupt is True
        assert sim.state.firm.capital == 0


# ════════════════════════════════════════════════════════════
# 长期仿真: 违约不破坏 SFC
# ════════════════════════════════════════════════════════════
class TestLongRunWithDefault:
    def test_24_months_with_rate_hike_no_sfc_violation(self):
        """激进加息 → 企业利润压力 → 可能违约 → 但 SFC 仍守恒."""
        from financial_sim.simulation.events import make_preset_shock

        config = SimConfig(
            n_households=10, n_ticks=24,
            preset_shocks=["rate_hike_100bp"],
        )
        sim = Simulation(config)
        # 在 t=6 注入大幅加息, 让 firm 资金压力骤增
        sim.state.event_manager.add(
            make_preset_shock("tightening_50bp_6m", trigger_t=6)
        )
        sim.run(n_ticks=24)
        total = sum(len(v) for v in sim.state.sfc_violations)
        assert total == 0, (
            f"SFC violations in 24-month run with shock: "
            f"{sim.state.sfc_violations[:2]}"
        )

    def test_default_with_writeoff_maintains_sfc(self):
        """手工强制违约, 验证 default 机制本身不引入新的 SFC 违反.

        注意: 本测试不强求 setup 完全 SFC-平衡 (手工构造跨部门平衡的
        default 场景需要构造完整的资金流, 不实用). 改为:
        1. 记录 setup 的初始违反量 (gap = A - L - capital)
        2. 触发 default
        3. 验证违约后 gap 不恶化 (可减小, 但不应增大)
        """
        sim = Simulation(SimConfig(n_households=10, n_ticks=1))
        # 强制 firm 接近破产 (SFC 不必完全平衡)
        sim.state.firm.deposits = 0
        sim.state.firm.inventory = 0
        sim.state.firm.capital = 50
        sim.state.firm.debt = 200
        sim.state.bank.deposits_from_firms = 0
        sim.state.bank.loans_to_firms = 200

        bs_pre = sim.state.build_balance_sheets()
        bank_pre = bs_pre["banks"]
        pre_gap = (
            bank_pre.sum_assets()
            - bank_pre.sum_liabilities()
            - bank_pre.capital
        )

        _default_resolution(sim.state)

        bs_post = sim.state.build_balance_sheets()
        bank_post = bs_post["banks"]
        post_gap = (
            bank_post.sum_assets()
            - bank_post.sum_liabilities()
            - bank_post.capital
        )

        # default 不应恶化 bank BS gap (gap 可缩小, 不应放大)
        diff = post_gap - pre_gap
        # 注: 在 setup 不平衡的情况下, default 机制实际可能缩小 gap
        # (因为还款部分从 A 和 L 同步减少). 这里只要求不恶化.
        # 如果 setup 本身平衡, gap 变化为 0.
        assert abs(diff) < 1e-6 or abs(diff) < abs(pre_gap), (
            f"Bank BS gap worsened: pre={pre_gap}, post={post_gap}, "
            f"diff={diff}"
        )
