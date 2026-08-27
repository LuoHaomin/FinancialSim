"""Labor market: search-matching with frictional unemployment.

Phase 1+ 设计 (AGENTS.md §3.2.4 + MARKETS.md):
- 默认行为: 摩擦失业 (search-matching)
  - 外生月度离职率 labor_separation_rate (默认 1%/月)
  - 岗位空缺 V = max(0, desired − current)
  - 匹配函数 f(θ) = 1 − exp(−η·θ), θ = V/U
  - 每月雇佣 = min(V, ⌈U·f⌉)
- 兼容模式 (labor_full_employment = True): 雇佣所有失业者 (legacy Phase 0)
- 工资方程 (Taylor + 菲利普斯斜率): 通胀指数化 + κ·(NAIRU−u)
- 向下工资粘性: 紧缩期降薪幅度减半

SFC 注记:
- 解雇/雇佣本身不发生资金流, 只动 firm.employees 计数
- 工资支付由 core.step._pay_wages 处理
"""
from __future__ import annotations

import math

from financial_sim.core.state import SimulationState
from financial_sim.utils.logging import get_logger

logger = get_logger(__name__)


class LaborMarket:
    """Phase 1+ 劳动市场: 摩擦匹配 + 工资议价."""

    # ── 工资 (向下粘性) ──
    NAIRU = 0.05                          # 自然失业率 5%
    WAGE_PRESSURE_COEFF = 0.10            # κ: 失业缺口→工资(年率)

    # ── 摩擦 (可由 config 覆盖) ──
    DEFAULT_SEPARATION_RATE = 0.01        # 月度离职率 (≈12%/年)
    DEFAULT_MATCHING_EFFICIENCY = 0.5

    # ── 配置开关 ──
    full_employment: bool = False         # True=legacy "雇所有人"
    separation_rate: float = DEFAULT_SEPARATION_RATE
    matching_efficiency: float = DEFAULT_MATCHING_EFFICIENCY
    wage_adjust_freq: int = 6             # 工资调整频率(月)
    wage_phillips_coeff: float = WAGE_PRESSURE_COEFF

    # ── Phase 3 Week B: 动态劳动需求 + 疤痕效应 ──
    adjust_up_speed: float = 0.25         # 每月最大扩员比例
    adjust_down_speed: float = 0.35       # 每月最大裁员比例 (向下更快)
    inventory_buffer: float = 0.20        # 目标产量相对销量缓冲
    demand_response_delay: int = 1        # 雇佣决策对销售的滞后 (月)
    scar_discount_rate: float = 0.01      # 长期失业: 每超宽限月工资折扣
    scar_grace_months: int = 6            # 疤痕宽限期
    scar_discount_cap: float = 0.30       # 折扣封顶

    def configure(
        self,
        full_employment: bool | None = None,
        separation_rate: float | None = None,
        matching_efficiency: float | None = None,
        wage_adjust_freq: int | None = None,
        wage_phillips_coeff: float | None = None,
        adjust_up_speed: float | None = None,
        adjust_down_speed: float | None = None,
        inventory_buffer: float | None = None,
        demand_response_delay: int | None = None,
        scar_discount_rate: float | None = None,
        scar_grace_months: int | None = None,
        scar_discount_cap: float | None = None,
    ) -> None:
        """运行时覆盖参数 (允许 config 与实例共存)."""
        if full_employment is not None:
            self.full_employment = full_employment
        if separation_rate is not None:
            self.separation_rate = separation_rate
        if matching_efficiency is not None:
            self.matching_efficiency = matching_efficiency
        if wage_adjust_freq is not None:
            self.wage_adjust_freq = wage_adjust_freq
        if wage_phillips_coeff is not None:
            self.wage_phillips_coeff = wage_phillips_coeff
        if adjust_up_speed is not None:
            self.adjust_up_speed = adjust_up_speed
        if adjust_down_speed is not None:
            self.adjust_down_speed = adjust_down_speed
        if inventory_buffer is not None:
            self.inventory_buffer = inventory_buffer
        if demand_response_delay is not None:
            self.demand_response_delay = max(0, int(demand_response_delay))
        if scar_discount_rate is not None:
            self.scar_discount_rate = scar_discount_rate
        if scar_grace_months is not None:
            self.scar_grace_months = scar_grace_months
        if scar_discount_cap is not None:
            self.scar_discount_cap = scar_discount_cap

    @classmethod
    def from_config(cls, config) -> LaborMarket:
        """从 SimConfig 构造并配置 (生产路径, 由 Simulation 调用)."""
        market = cls()
        market.configure(
            full_employment=getattr(config, "labor_full_employment", None),
            separation_rate=getattr(config, "labor_separation_rate", None),
            matching_efficiency=getattr(config, "labor_matching_efficiency", None),
            wage_adjust_freq=getattr(config, "labor_wage_adjust_freq", None),
            wage_phillips_coeff=getattr(config, "labor_wage_phillips_coeff", None),
            adjust_up_speed=getattr(config, "labor_adjust_up_speed", None),
            adjust_down_speed=getattr(config, "labor_adjust_down_speed", None),
            inventory_buffer=getattr(config, "labor_inventory_buffer", None),
            demand_response_delay=getattr(
                config, "labor_demand_response_delay", None
            ),
            scar_discount_rate=getattr(config, "wage_scar_discount_rate", None),
            scar_grace_months=getattr(config, "wage_scar_grace_months", None),
            scar_discount_cap=getattr(config, "wage_scar_discount_cap", None),
        )
        return market

    # ════════════════════════════════════════════════════════════
    # 主入口
    # ════════════════════════════════════════════════════════════
    def clear(self, state: SimulationState) -> None:
        """月度劳动市场出清.

        顺序:
        1. 外生离职 (用 RNGManager 'labor_separation' 流抽样保证可复现)
        2. 雇佣 (legacy 全雇佣 或 摩擦匹配; Phase 3: 跨企业分配岗位)
        3. 工资调整 (按 wage_adjust_freq 周期)
        4. 失业计时推进

        注: 不在内部从 state.config 自动 configure, 以保持测试隔离性.
        调用方应在构造仿真时一次性配置 (见 Simulation._build_state).
        """
        if not state.firms:
            return

        # 0. 动态劳动需求: 销售驱动更新目标就业 + 收缩部门裁员入池
        self._update_labor_demand(state)

        # 1. 外生离职
        self._apply_separations(state)

        # 2. 雇佣
        if self.full_employment:
            self._full_employment_hire(state)
        else:
            self._frictional_hire(state)

        # 3. 工资调整
        if state.t > 0 and state.t % self.wage_adjust_freq == 0:
            self._adjust_wages(state)

        # 4. 失业计时推进
        for h in state.households:
            h.tick_unemployment()

    # ════════════════════════════════════════════════════════════
    # 0. 动态劳动需求 (Week B): 销售 → 目标产量 → 目标就业 → 裁员
    # ════════════════════════════════════════════════════════════
    def _update_labor_demand(self, state: SimulationState) -> None:
        """各企业的目标就业由 (滞后的) 销售额决定, 调整速度上下不对称.

        L* = 滞后销量 ×(1+库存缓冲) / (A × P)   (线性生产下的保本就业)
        调整: desired = L + clamp(L* − L, −down·L, +up·L)
        目标下调部分立即裁员 (员工进入失业池, 等待匹配再配置).
        """
        for firm in state.firms:
            if firm.is_bankrupt:
                continue
            hist = getattr(firm, "demand_history", None)
            if not hist:
                # 无需求历史时退回销售历史, 再退回当月销售额
                hist = getattr(firm, "sales_history", None)
                base_val = getattr(firm, "last_sales", 0.0)
            else:
                base_val = 0.0
            if hist:
                idx = len(hist) - 1 - self.demand_response_delay
                delayed_sales = hist[idx] if idx >= 0 else hist[0]
            else:
                delayed_sales = base_val

            if delayed_sales <= 0 or firm.price <= 0 or firm.productivity <= 0:
                target_l = float(firm.employees)  # 无销售信号: 维持现状
            else:
                target_output = delayed_sales * (1.0 + self.inventory_buffer)
                target_l = (
                    target_output / firm.price / firm.productivity
                )

            lo = firm.employees - self.adjust_down_speed * firm.employees
            hi = firm.employees + self.adjust_up_speed * firm.employees
            desired = int(round(min(max(target_l, lo), hi)))
            desired = max(desired, 0)
            firm.baseline_employees = desired

            # 立即裁掉超出目标的部分 (裁员快于招聘的不对称性)
            excess = firm.employees - desired
            if excess > 0:
                staff = [
                    h for h in state.households
                    if h.employed and h.employer_id == firm.id
                ]
                for h in staff[:excess]:
                    h.lose_job()
                firm.fire(excess)

    # ════════════════════════════════════════════════════════════
    # 1. 外生离职
    # ════════════════════════════════════════════════════════════
    def _apply_separations(self, state: SimulationState) -> None:
        """按 separation_rate 随机解雇员工 (跨企业, 按雇主归属扣减)."""
        employed = [h for h in state.households if h.employed]
        if not employed or not state.firms:
            return
        rate = self.separation_rate
        if rate <= 0:
            return

        mgr = getattr(state, "rng_manager", None)
        if mgr is not None:
            rng = mgr.stream("labor_separation")
            n_separated = int(rng.binomial(len(employed), rate))
            idx = (
                {int(i) for i in rng.choice(
                    len(employed), size=n_separated, replace=False)}
                if n_separated > 0 else set()
            )
        else:
            # Fallback: 期望值, 不可复现
            n_separated = int(round(len(employed) * rate))
            idx = set(range(min(n_separated, len(employed))))

        fired_per_firm: dict[str, int] = {}
        for i, h in enumerate(employed):
            if i not in idx:
                continue
            employer_id = h.employer_id
            h.lose_job()
            if employer_id is not None:
                fired_per_firm[employer_id] = fired_per_firm.get(employer_id, 0) + 1
        for f in state.firms:
            n = fired_per_firm.get(f.id, 0)
            if n > 0:
                f.fire(n)

    # ════════════════════════════════════════════════════════════
    # 2a. Legacy: 全雇佣
    # ════════════════════════════════════════════════════════════
    def _full_employment_hire(self, state: SimulationState) -> None:
        """雇佣所有失业者 (Phase 0 行为, 仅用于回归测试)."""
        if not state.firms:
            return
        for h in state.households:
            if not h.employed:
                firm = state.firms[0]  # legacy: 单一雇主
                firm.hire(1)
                h.find_job(
                    sector=firm.sector, wage=firm.wage_offered,
                    employer_id=firm.id,
                )

    def _frictional_hire(self, state: SimulationState) -> None:
        """搜索-匹配模型 (跨企业): f(θ) = 1 − exp(−η·V/U).

        招聘命中率由总紧度决定; 命中的名额按各企业岗位空缺占比分配
        (FIFO 取失业者, 确定性顺序).
        """
        if not state.firms:
            return

        vacancies_per_firm = {
            f.id: max(
                0,
                (f.baseline_employees if f.baseline_employees > 0
                 else len(state.households)) - f.employees,
            )
            for f in state.firms if not f.is_bankrupt
        }
        total_vacancies = sum(vacancies_per_firm.values())
        unemployed_hh = [h for h in state.households if not h.employed]
        n_unemployed = len(unemployed_hh)
        if total_vacancies == 0 or n_unemployed == 0:
            return

        theta = total_vacancies / n_unemployed
        f_match = 1.0 - math.exp(-self.matching_efficiency * theta)
        n_hires = min(total_vacancies, int(math.ceil(n_unemployed * f_match)))

        # 名额按空缺比例分配到企业; 舍入余量给空缺最多的企业
        alloc = {
            fid: int(n_hires * v / total_vacancies)
            for fid, v in vacancies_per_firm.items()
        }
        remainder = n_hires - sum(alloc.values())
        if remainder > 0:
            top = max(vacancies_per_firm, key=lambda k: vacancies_per_firm[k])
            alloc[top] += remainder

        hire_iter = iter(unemployed_hh)
        firm_by_id = {f.id: f for f in state.firms}
        hired_total = 0
        for fid, n in alloc.items():
            firm = firm_by_id[fid]
            for _ in range(n):
                h = next(hire_iter, None)
                if h is None:
                    break
                effective_wage = self._scar_discounted_wage(firm.wage_offered, h)
                firm.hire(1)
                h.find_job(
                    sector=firm.sector, wage=effective_wage,
                    employer_id=firm.id,
                )
                hired_total += 1

        logger.debug(
            f"  labor: V={total_vacancies}, U={n_unemployed}, "
            f"θ={theta:.2f}, f={f_match:.2f}, hires={hired_total}"
        )

    # ════════════════════════════════════════════════════════════
    # 疤痕效应 (Week B): 长期失业者再就业时接受工资折扣
    # ════════════════════════════════════════════════════════════
    def _scar_discounted_wage(
        self, posted_wage: float, household: object,
    ) -> float:
        """w_eff = w × (1 − min(cap, rate × max(0, 失业月数 − 宽限期)))."""
        dur = getattr(household, "unemployment_duration", 0)
        over = max(0, dur - self.scar_grace_months)
        discount = min(
            self.scar_discount_cap, self.scar_discount_rate * over
        )
        return posted_wage * (1.0 - discount)

    # ════════════════════════════════════════════════════════════
    # 3. 工资调整
    # ════════════════════════════════════════════════════════════
    def _adjust_wages(self, state: SimulationState) -> None:
        """基于通胀预期 + 失业缺口的工资方程 (向下粘性).

        Δw/w = π_exp / 2 + κ · (NAIRU − u)   (紧缩期 κ × 0.5)
        所有企业同步调整 (单一劳动市场议价), 并同步员工合同工资.
        """
        if not state.firms:
            return

        unemployment = state.unemployment_rate_calc()
        unemployment_gap = self.NAIRU - unemployment  # >0 = 劳动力紧张

        exp_module = getattr(state, "inflation_expectation", None)
        indexation = (exp_module.value / 2.0) if exp_module is not None else 0.0

        if unemployment_gap >= 0:
            pressure = indexation + self.wage_phillips_coeff * unemployment_gap
        else:
            # 向下粘性: 失业>NAIRU 时降薪减半且无指数化上推
            pressure = 0.5 * (
                indexation + self.wage_phillips_coeff * unemployment_gap
            )

        employer_by_id = {f.id: f for f in state.firms}
        for firm in state.firms:
            firm.wage_offered *= 1.0 + pressure
        for h in state.households:
            if h.employed and h.employer_id in employer_by_id:
                h.wage = employer_by_id[h.employer_id].wage_offered


__all__ = ["LaborMarket"]
