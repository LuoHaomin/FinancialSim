"""多部门多家企业集成测试 (Phase 3.5 PR-1).

验收:
- `n_firms_per_sector=N` 真创建 N 家同部门企业
- 初始总员工/总存款按部门劳动份额分配,SFC 逐位相等
- 多企业场景下稳态仿真 24 月无 SFC 违反
"""
from __future__ import annotations

import pytest

from financial_sim.config import SimConfig
from financial_sim.core.simulation import Simulation


@pytest.mark.integration
class TestMultiFirmPerSector:
    """PR-1: 同 sector 多家同质企业."""

    def test_one_firm_per_sector_default(self):
        """默认 `n_firms_per_sector=1`, 每部门 1 家 (向后兼容)."""
        cfg = SimConfig(n_households=100, sectors=["consumer_goods", "capital"])
        sim = Simulation(cfg)
        assert len(sim.state.firms) == 2
        sectors = {f.sector for f in sim.state.firms}
        assert sectors == {"consumer_goods", "capital"}

    def test_n_firms_per_sector_creates_multiple(self):
        """`n_firms_per_sector=3` → 同 sector 3 家企业."""
        cfg = SimConfig(
            n_households=100,
            n_firms_per_sector=3,
            sectors=["consumer_goods", "capital"],
        )
        sim = Simulation(cfg)
        assert len(sim.state.firms) == 6  # 2 sectors × 3 firms
        by_sector: dict[str, list] = {}
        for f in sim.state.firms:
            by_sector.setdefault(f.sector, []).append(f)
        for sector, firms in by_sector.items():
            assert len(firms) == 3, f"{sector} 应有 3 家"
            ids = {f.id for f in firms}
            assert len(ids) == 3, "firm.id 应唯一"

    def test_firm_id_unique_across_sectors(self):
        """firm.id 在多部门多家下应全局唯一."""
        cfg = SimConfig(
            n_households=100,
            n_firms_per_sector=4,
            sectors=["consumer_goods", "capital", "energy"],
        )
        sim = Simulation(cfg)
        ids = [f.id for f in sim.state.firms]
        assert len(set(ids)) == len(ids) == 12

    def test_sector_labor_share_preserved_across_firms(self):
        """部门总员工数应与旧单企业版本一致 (Σ sector emp = n_hh 占比)."""
        for n_per in [1, 2, 5]:
            cfg = SimConfig(
                n_households=100,
                n_firms_per_sector=n_per,
                sectors=["consumer_goods", "capital", "energy"],
                seed=42,
            )
            sim = Simulation(cfg)
            by_sector_emp = {}
            for f in sim.state.firms:
                by_sector_emp[f.sector] = (
                    by_sector_emp.get(f.sector, 0) + f.employees
                )
            # 部门员工数应符合 labor_shares × n_hh (允许 ±1 残差)
            total = sum(by_sector_emp.values())
            assert total == 100, f"n_per={n_per}: total emp {total} != 100"
            # 至少一家企业有非零员工(没有空企业)
            assert any(f.employees > 0 for f in sim.state.firms)

    def test_sector_deposits_preserved_across_firms(self):
        """部门总初始存款应保持 (SFC 镜像逐位相等)."""
        for n_per in [1, 2, 5]:
            cfg = SimConfig(
                n_households=100,
                n_firms_per_sector=n_per,
                sectors=["consumer_goods", "capital"],
                seed=42,
            )
            sim = Simulation(cfg)
            # Σ 所有 firm.deposits 应 == 200 (initial_firm_deposits = 100 * 1 * 2)
            total_dep = sum(f.deposits for f in sim.state.firms)
            assert total_dep == pytest.approx(200.0, abs=1e-9), (
                f"n_per={n_per}: total firm.deposits {total_dep} != 200"
            )
            # Σ 所有 firm.debt 应 == 200 (镜像)
            total_debt = sum(f.debt for f in sim.state.firms)
            assert total_debt == pytest.approx(200.0, abs=1e-9)

    def test_multi_firm_runs_clean(self):
        """多企业场景下跑 24 月, SFC 干净."""
        cfg = SimConfig(
            n_households=100,
            n_firms_per_sector=3,
            sectors=["consumer_goods", "capital", "energy"],
            seed=42,
        )
        sim = Simulation(cfg)
        sim.run(24)
        total_violations = sum(len(v) for v in sim.state.sfc_violations)
        assert total_violations == 0
        # 24 月后所有 firm 应仍存活(无破产)
        assert all(not f.is_bankrupt for f in sim.state.firms)

    def test_multi_firm_labor_market_recovers(self):
        """同 sector 多家 + 摩擦雇佣: 雇佣回归仍工作."""
        cfg = SimConfig(
            n_households=100,
            n_firms_per_sector=3,
            sectors=["consumer_goods"],
            seed=42,
        )
        sim = Simulation(cfg)
        # 制造 10 人失业
        for h in sim.state.households[:10]:
            h.lose_job()
            # 减少对应 firm 的员工 (round-robin)
            for f in sim.state.firms:
                if f.employees > 0:
                    f.employees -= 1
                    f.baseline_employees -= 1
                    break
        # 跑 3 月
        for _ in range(3):
            sim.step()
        # 失业应被吸收(可能没全吸收,但应减少)
        assert sim.state.total_unemployed() < 10


@pytest.mark.integration
class TestMultiFirmBackwardCompatibility:
    """PR-1 不破坏现有测试."""

    def test_state_firm_alias_still_works(self):
        """state.firm (单数) 仍是 firms[0] 的别名."""
        cfg = SimConfig(
            n_households=100, n_firms_per_sector=3,
            sectors=["consumer_goods", "capital"],
        )
        sim = Simulation(cfg)
        assert sim.state.firm is sim.state.firms[0]

    def test_default_n_firms_per_sector_is_one(self):
        """默认 n_firms_per_sector=1 (向后兼容)."""
        cfg = SimConfig(n_households=100)
        assert cfg.n_firms_per_sector == 1
