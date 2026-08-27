"""monthly_tick: 编排一个月的仿真流程.

Phase 1 版 (在 Phase 0 骨架上扩展):
1. 央行决策 (Taylor Rule, 参数来自 config)
2. 劳动市场出清 (雇佣 + 工资调整, 工资参考通胀预期)
3. 工资支付 (firm → HH)
4. 家庭消费 (流动性约束)
5. 商品市场出清 (库存规则或卡尔沃定价) + 库存更新
6. 银行循环 (存贷利息 → 资本)
7. 政府循环 (税收 + 支出 + 救济; 赤字经 CB 购债融资)
8. 企业资本循环 (折旧 + 加速器投资)
9. 宏观聚合 (产出/失业/通胀 + 永久收入/预期更新)
10. SFC 校验

SFC 注记: 所有跨部门资金流在此处双边镜像记账, 保证
validate_sfc 的 6 项检查每 tick 通过.
"""
from __future__ import annotations

from financial_sim.core.state import SimulationState
from financial_sim.markets.goods import GoodsMarket
from financial_sim.markets.labor import LaborMarket
from financial_sim.monetary.sfc import validate_sfc
from financial_sim.utils.logging import get_logger

logger = get_logger(__name__)


def _cfg(state: SimulationState, name: str, default: float | int | bool) -> float | int | bool:
    """从 state.config 读参数; config 缺失时用默认值 (便于单元测试)."""
    cfg = state.config
    value = getattr(cfg, name, default)
    return default if value is None else value


def monthly_tick(
    state: SimulationState,
    goods_market: GoodsMarket | None = None,
    labor_market: LaborMarket | None = None,
) -> None:
    """执行一个月的仿真."""
    if goods_market is None:
        goods_market = GoodsMarket()
    if labor_market is None:
        labor_market = LaborMarket()

    logger.debug(f"=== Tick {state.t} start ===")

    _apply_events(state)
    _cb_decisions(state)
    labor_market.clear(state)
    _pay_wages(state)
    _household_consumption(state)
    goods_market.update_inventory(state)
    goods_market.clear(state)  # 定价基于月末库存 (生产补充后)
    if _cfg(state, "calvo_price_prob", 0.0):
        _maybe_calvo_pricing(state, goods_market)
    _bank_cycle(state)
    _government_cycle(state)
    _firm_capital_cycle(state)
    _default_resolution(state)  # Phase 1+: 违约检测 + 处置 + 恢复
    _aggregate_macros(state)
    _validate_sfc(state)

    state.t += 1


# ════════════════════════════════════════════════════════════
# 0. 事件系统: 在 CB 决策之前注入参数冲击
# ════════════════════════════════════════════════════════════
def _apply_events(state: SimulationState) -> None:
    """从 EventManager 触发当前 tick 的所有 ShockEvent, 并记录日志."""
    mgr = getattr(state, "event_manager", None)
    if mgr is None:
        return
    fired = mgr.apply_to_state(state, state.t)
    for ev in fired:
        state.shock_log.append(
            {"t": state.t, "name": ev.name, "channel": ev.channel,
             "magnitude": ev.magnitude}
        )


# ════════════════════════════════════════════════════════════
# 1. CB 决策 (Taylor Rule)
# ════════════════════════════════════════════════════════════
def _cb_decisions(state: SimulationState) -> None:
    """Taylor Rule 设定政策利率 (参数从 config 读取)."""
    cb = state.central_bank
    assert cb is not None
    smoothing = float(_cfg(state, "taylor_smoothing", 0.85))
    floor = float(_cfg(state, "taylor_rate_floor", -0.005))
    cb.policy_rate = cb.taylor_rule(
        inflation=state.inflation_yoy,
        output_gap=state.output_gap,
        smoothing=smoothing,
        rate_floor=floor,
    )


# ════════════════════════════════════════════════════════════
# 工具: 读取事件系统覆盖值 (无 manager 时返回原值)
# ════════════════════════════════════════════════════════════
def _effective_gov_multiplier(state: SimulationState) -> float:
    mgr = getattr(state, "event_manager", None)
    if mgr is None:
        return 1.0
    return mgr.get_gov_spending_multiplier(state)


def _effective_income_tax_rate(state: SimulationState, base: float) -> float:
    mgr = getattr(state, "event_manager", None)
    if mgr is None:
        return base
    return mgr.get_income_tax_rate(state, base)


# ════════════════════════════════════════════════════════════
# 3. 工资支付
# ════════════════════════════════════════════════════════════
def _pay_wages(state: SimulationState) -> None:
    """Firm 给员工发工资, 钱从 firm.deposits 转到 hh.deposits."""
    firm = state.firm
    bank = state.bank
    assert firm is not None
    assert bank is not None

    employed_hh = [h for h in state.households if h.employed]
    if not employed_hh:
        return

    total_wages = firm.employees * firm.wage_offered

    # 存款不足时向银行借款补足 (债务资本化, 不动资本)
    if firm.deposits < total_wages:
        shortfall = total_wages - firm.deposits
        firm.debt += shortfall
        bank.loans_to_firms += shortfall
        bank.deposits_from_firms += shortfall
        firm.deposits += shortfall

    firm.deposits -= total_wages
    bank.deposits_from_firms -= total_wages
    bank.deposits_from_hh += total_wages

    wage_per_hh = total_wages / len(employed_hh)
    for h in employed_hh:
        h.income = wage_per_hh
        h.deposits += wage_per_hh


# ════════════════════════════════════════════════════════════
# 4. 家庭消费
# ════════════════════════════════════════════════════════════
def _household_consumption(state: SimulationState) -> None:
    """HH 决定消费, 受流动性约束 (不能超过存款)."""
    firm = state.firm
    bank = state.bank
    assert firm is not None
    assert bank is not None

    total_consumption = 0.0
    for h in state.households:
        c = min(h.decide_consumption(), h.deposits)
        c = max(c, 0.0)
        h.deposits -= c
        total_consumption += c

    if total_consumption > 0:
        firm.deposits += total_consumption
        firm.inventory = max(0.0, firm.inventory - total_consumption)
        bank.deposits_from_hh -= total_consumption
        bank.deposits_from_firms += total_consumption
    state.last_month_sales = total_consumption


# ════════════════════════════════════════════════════════════
# 5b. 卡尔沃定价 (可选, calvo_price_prob > 0 时启用)
# ════════════════════════════════════════════════════════════
def _maybe_calvo_pricing(
    state: SimulationState,
    goods_market: GoodsMarket,
) -> None:
    """以概率 θ 把价格调到目标加成价 (库存规则已在 clear() 生效).

    抽签使用 RNGManager 的 'pricing' 流; 没有 manager 时跳过.
    """
    firm = state.firm
    assert firm is not None
    mgr = getattr(state, "rng_manager", None)
    if mgr is None:
        return
    rng = mgr.stream("pricing")
    firm.maybe_calvo_reprice(float(rng.random()))
    _ = goods_market


# ════════════════════════════════════════════════════════════
# 6. 银行循环: 利率定价 + 利息流
# ════════════════════════════════════════════════════════════
def _bank_cycle(state: SimulationState) -> None:
    """银行按月收贷款利息、付存款利息, 净额进资本.

    记账规则 (两侧镜像, 保证 SFC):
    - 收贷款利息 (firm 有存款):   firm.deposits −i / bank.deposits_from_firms −i / bank.capital +i
      (firm 无存款): 债务资本化   firm.debt +i / bank.loans_to_firms +i
    - 付存款利息: hh/firm 存款 +d / 对应负债 +d / bank.capital −d
    """
    bank = state.bank
    firm = state.firm
    cb = state.central_bank
    assert bank is not None
    assert firm is not None
    assert cb is not None

    loan_rate, deposit_rate = bank.set_rates(cb.policy_rate)

    # ── 贷款利息 ──
    loan_interest = bank.loans_to_firms * loan_rate / 12.0
    if loan_interest > 0:
        if firm.deposits >= loan_interest:
            # 现金支付: 借款人存款 −i / 银行负债 −i / 资本 +i
            firm.deposits -= loan_interest
            bank.deposits_from_firms -= loan_interest
            bank.book_loan_interest_income(loan_interest)
        else:
            # 资本化: 计入借款人债务 / 银行应收资产 ↑;
            # 权责发生制下同时确认利息收入进资本, 保持 A = L + capital
            firm.debt += loan_interest
            bank.loans_to_firms += loan_interest
            bank.book_loan_interest_income(loan_interest)

    # ── 存款利息 ──
    int_hh = bank.deposits_from_hh * deposit_rate / 12.0
    int_firm = bank.deposits_from_firms * deposit_rate / 12.0
    if int_hh > 0:
        n_emp = max(1, sum(1 for h in state.households if h.deposits > 0))
        per_hh = int_hh / n_emp
        for h in state.households:
            if h.deposits > 0:
                h.deposits += per_hh
        bank.deposits_from_hh += int_hh
    if int_firm > 0:
        firm.deposits += int_firm
        bank.deposits_from_firms += int_firm
    bank.book_deposit_interest_expense(int_hh + int_firm)


# ════════════════════════════════════════════════════════════
# 7. 政府: 税收 + 支出 + 救济 + 赤字融资
# ════════════════════════════════════════════════════════════
def _government_cycle(state: SimulationState) -> None:
    """完整政府预算: G + TR = T + ΔB.

    记账 (净注资 J = G + TR − T, 经 CB 购债/卖债完成):
    - J > 0 (赤字): gov.debt += J, cb.gov_bonds += J,
      cb.bank_reserves += J ↔ bank.reserves += J,
      收款人存款 += 各自所得 ↔ bank.deposits_* += 同额
    - J < 0 (盈余): 反向操作, 退出等额国债并回笼私人存款
    """
    if not bool(_cfg(state, "fiscal_enabled", True)):
        return

    gov = state.government
    bank = state.bank
    firm = state.firm
    cb = state.central_bank
    assert gov is not None
    assert bank is not None
    assert firm is not None
    assert cb is not None

    income_tax_rate_base = float(_cfg(state, "income_tax_rate", 0.25))
    income_tax_rate = _effective_income_tax_rate(state, income_tax_rate_base)
    corp_tax_rate = float(_cfg(state, "corp_tax_rate", 0.21))

    # ── 收入税 (从工资中预扣; 同时下调 h.income 为税后口径) ──
    total_income_tax = 0.0
    for h in state.households:
        if h.employed and h.income > 0:
            t = h.income * income_tax_rate
            h.deposits -= t
            h.income -= t
            total_income_tax += t
    bank.deposits_from_hh -= total_income_tax

    # ── 公司税 ──
    corp_tax = max(0.0, firm.profit()) * corp_tax_rate
    corp_tax = min(corp_tax, firm.deposits)
    firm.deposits -= corp_tax
    bank.deposits_from_firms -= corp_tax
    gov.tax_revenue = total_income_tax + corp_tax

    # ── 政府购买 G (流入 firm) 与失业救济 TR (流入失业家庭) ──
    g_spending = float(_cfg(state, "gov_spending_monthly", 0.0))
    if g_spending <= 0:
        share = float(_cfg(state, "gov_spending_share_gdp", 0.45))
        g_spending = share * state.potential_gdp
    # Phase 1+: 应用事件系统的乘数 (fiscal_austerity / fiscal_stimulus)
    g_spending *= _effective_gov_multiplier(state)
    benefit_per_hh = float(_cfg(state, "gov_unemployment_benefit", 0.0))
    unemployed = [h for h in state.households if not h.employed]
    total_benefits = benefit_per_hh * len(unemployed)
    if total_benefits > 0 and unemployed:
        per_hh = total_benefits / len(unemployed)
        for h in unemployed:
            h.deposits += per_hh
            h.income = per_hh
        bank.deposits_from_hh += total_benefits
    if g_spending > 0:
        firm.deposits += g_spending
        bank.deposits_from_firms += g_spending

    gov.transfers = total_benefits
    gov.gov_spending = g_spending

    # ── 赤字融资: 发行国债给 CB, 换成准备金注入银行体系 ──
    injection = g_spending + total_benefits - gov.tax_revenue
    if abs(injection) > 0:
        gov.debt += injection            # 发行(+)/回购(−)
        cb.gov_bonds += injection        # CB 承接
        cb.bank_reserves += injection    # 准备金注入/回笼
        bank.reserves += injection       # 与 CB 账目镜像


# ════════════════════════════════════════════════════════════
# 8. 企业资本循环: 折旧 + 投资
# ════════════════════════════════════════════════════════════
def _firm_capital_cycle(state: SimulationState) -> None:
    """K ← K(1−δ) 后执行加速器投资 (deposits → capital, SFC 中性)."""
    firm = state.firm
    assert firm is not None
    firm.depreciation_rate = float(_cfg(state, "depreciation_rate", 0.01))
    firm.investment_sensitivity = float(_cfg(state, "investment_sensitivity", 0.5))
    firm.depreciate()
    investment = firm.decide_investment()
    if investment > 0:
        firm.invest(investment)


# ════════════════════════════════════════════════════════════
# 8b. 违约处置: 触发 → 破产 → 银行核销 → 恢复注资
# ════════════════════════════════════════════════════════════
DEFAULT_COOLDOWN_MONTHS = 6  # 破产后 N 月再注资 (留出"重组"窗口)


def _default_resolution(state: SimulationState) -> None:
    """Phase 1+ 简化违约流程.

    检测 → 处置 → 银行核销 → 计时 → (cool-down 后) 再注资.
    SFC 注记: declare_bankruptcy 已把 firm.debt 减为 0, 此时银行核销贷款与
    资本同步下降, 资产-负债恒等式保持.
    """
    if not bool(_cfg(state, "enable_default", True)):
        # 仍推进计时, 否则后续逻辑可能误判 (但当前简化下不做破产)
        return

    firm = state.firm
    bank = state.bank
    if firm is None or bank is None:
        return

    # ── 1. 检测违约 (净资产 < 阈值 且 未破产) ──
    if not firm.is_bankrupt and firm.is_default():
        logger.info(f"Default detected at t={state.t}: equity={firm.equity():.2f}")
        detail = firm.declare_bankruptcy()

        # 银行镜像 (SFC 同步):
        # 还款部分: firm 用存款还债
        #   bank.deposits_from_firms -= repaid, bank.loans_to_firms -= repaid
        #   A −X (loans), L −X (deposits); capital 不变 ✓
        # 注: 准备金不变 (SFC 模型中借贷流程不动准备金)
        if detail["debt_repaid"] > 0:
            bank.deposits_from_firms = max(
                0.0, bank.deposits_from_firms - detail["debt_repaid"]
            )
            bank.loans_to_firms = max(
                0.0, bank.loans_to_firms - detail["debt_repaid"]
            )

        # 未偿还部分: 银行核销 (loans 减, capital 减, npl 清零)
        #   A −X (loans), capital −X; L 不变 ✓
        if detail["debt_unpaid"] > 0:
            bank.mark_npl(detail["debt_unpaid"])
            written = bank.write_off_loan(detail["debt_unpaid"])
            logger.info(
                f"  Bank wrote off {written:.2f}, "
                f"CAR now {bank.car():.3f}"
            )

        # 解雇所有员工 (联动 HH 失业状态)
        for h in state.households:
            if h.employed and h.sector == firm.sector:
                h.lose_job()

    # ── 2. 破产计时 + 恢复注资 ──
    if firm.is_bankrupt:
        firm.tick_bankruptcy()
        cooldown = int(_cfg(state, "default_cooldown_months", DEFAULT_COOLDOWN_MONTHS))
        if firm.months_bankrupt >= cooldown:
            # 银行新贷款注入资本: A 增加 (firm.deposits + capital) 与 L 同步 (debt + bank 负债)
            recap_amount = float(_cfg(state, "recovery_capital_amount", 100.0))
            bank.loans_to_firms += recap_amount
            bank.deposits_from_firms += recap_amount
            firm.recapitalize(recap_amount)
            logger.info(
                f"Recapitalized at t={state.t}: capital={recap_amount:.2f}"
            )


# ════════════════════════════════════════════════════════════
# 9. 宏观聚合
# ════════════════════════════════════════════════════════════
def _aggregate_macros(state: SimulationState) -> None:
    """计算并存储宏观变量: GDP、失业、通胀、预期、永久收入."""
    firm = state.firm

    state.real_gdp = state.total_output()
    state.nominal_gdp = state.real_gdp * firm.price if firm else 0.0
    state.unemployment_rate = state.unemployment_rate_calc()
    state.output_gap = (
        (state.real_gdp - state.potential_gdp) / state.potential_gdp
        if state.potential_gdp > 0
        else 0.0
    )

    _update_inflation(state)

    # 价格水平进入历史 (通胀计算依赖)
    if firm is not None:
        state.price_level = firm.price
    state.price_level_history.append(state.price_level)

    for h in state.households:
        h.update_permanent_income()

    exp_mod = getattr(state, "inflation_expectation", None)
    if exp_mod is not None:
        target = float(_cfg(state, "target_inflation", 0.02))
        exp_mod.update(state.inflation_yoy, target_inflation=target)

    state.snapshot_macro()


def _update_inflation(state: SimulationState) -> None:
    """年化通胀: 有 ≥13 个月价格史时用同比; 否则用环比 × 12 外推."""
    hist = state.price_level_history
    current = state.price_level
    if len(hist) >= 12:
        year_ago = hist[-12]
        state.inflation_yoy = current / year_ago - 1 if year_ago > 0 else 0.0
    elif len(hist) >= 1 and hist[-1] > 0:
        state.inflation_yoy = (current / hist[-1] - 1) * 12


# ════════════════════════════════════════════════════════════
# 10. SFC 校验
# ════════════════════════════════════════════════════════════
def _validate_sfc(state: SimulationState) -> None:
    """构造 BS 字典并校验 SFC."""
    bs_dict = state.build_balance_sheets()
    errors = validate_sfc(bs_dict)
    if errors:
        logger.warning(f"SFC violations at tick {state.t}: {errors}")
        state.sfc_violations.append(errors)
