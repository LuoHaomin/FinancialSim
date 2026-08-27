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
from financial_sim.monetary.sfc import validate_housing_stock, validate_sfc
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
    _consumer_credit_cycle(state)         # Phase 3 前置 P0-a: 消费贷申请 + 配给 + 还款
    _household_consumption(state)
    goods_market.update_inventory(state)
    goods_market.clear(state)  # 定价基于月末库存 (生产补充后)
    if _cfg(state, "calvo_price_prob", 0.0):
        _maybe_calvo_pricing(state, goods_market)
    _bank_cycle(state)
    _housing_cycle(state)                 # Phase 2: 抵押 + 房租 + 价格
    _government_cycle(state)
    _bond_cycle(state)                    # Phase 3 前置 P0-b: 发债 + 付息
    _firm_capital_cycle(state)
    _default_resolution(state)            # Phase 1+: 违约检测 + 处置 + 恢复
    _mortgage_default_check(state)        # Phase 2: 房贷违约 → 银行 NPL
    _interbank_cycle(state)               # Phase 2: 同业利息 (n_banks>1 时生效)
    _fire_sale_and_failure(state)         # Phase 2: fire-sale + 失败处置
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
# 3b. 消费信贷市场 (P0-a)
# ════════════════════════════════════════════════════════════
def _consumer_credit_cycle(state: SimulationState) -> None:
    """家庭消费信贷循环: 申请 → 配给 → 发放 → 还款.

    三步 (均在同一 tick 内):
      A. 还款: 现有贷款的等额本息, 利息 → 银行资本, 本金 → 减贷款余额
      B. 申请: 家庭按"流动性缺口"提出新贷请求
      C. 配给: 银行按 DTI + lending_fraction 筛选批准

    SFC 注记:
      还款: hh.deposits ↓payment / hh.consumer_loan ↓principal
            bank.deposits_from_hh ↓payment / bank.loans_to_hh ↓principal
            bank.capital ↑interest (按权责发生制)
      发放: hh.deposits ↑L / hh.consumer_loan ↑L / bank.loans_to_hh ↑L
            bank.deposits_from_hh ↑L (凭空创造存款, 内生信用)
    """
    if not bool(_cfg(state, "enable_consumer_credit", False)):
        return
    if state.bank is None or state.central_bank is None:
        return

    bank = state.bank
    cb = state.central_bank
    cb_rate = cb.policy_rate if cb is not None else 0.025
    loan_rate = cb_rate + float(_cfg(state, "consumer_loan_spread", 0.05))
    term = int(_cfg(state, "consumer_loan_term_months", 60))
    dti_limit = float(_cfg(state, "consumer_loan_dti_limit", 0.40))
    lending_fraction = float(_cfg(state, "consumer_loan_lending_fraction", 0.7))
    income_mult = 3.0  # 与 markets/credit.py 默认一致

    # ── A. 等额本息还款 ──
    for h in state.households:
        if h.consumer_loan <= 0:
            continue
        r = loan_rate / 12.0
        n = term
        payment = h.consumer_loan * r / (1.0 - (1.0 + r) ** (-n))
        # 简化 —分摊: 利息 = 余额 × 月率; 本金 = 余下
        interest = h.consumer_loan * r
        principal = payment - interest
        affordable = min(payment, max(0.0, h.deposits))
        if affordable < payment:
            # 断供: 把未付部分资本化 (Phase 1 简化, 不触发违约 — Phase 3 再加)
            affordable = payment
            h.deposits -= payment
        else:
            h.deposits -= payment
        h.consumer_loan = max(0.0, h.consumer_loan - principal)
        bank.deposits_from_hh = max(0.0, bank.deposits_from_hh - payment)
        bank.loans_to_households = max(
            0.0, bank.loans_to_households - principal
        )
        bank.capital += interest  # 利息收入入资本

    # ── B + C. 申请 + 配给 ──
    approved_total = 0.0
    requests = []
    for h in state.households:
        if h.income <= 0:
            continue
        gap = max(0.0, h.income - h.deposits)
        desired = min(income_mult * h.income, gap)
        if desired < 1e-3:
            continue
        new_balance = h.consumer_loan + desired
        if new_balance / h.income > dti_limit:
            desired = max(0.0, dti_limit * h.income - h.consumer_loan)
            if desired < 1e-3:
                h.credit_denied_months += 1
                continue
        requests.append((h, desired))

    # 简化配给: 随机拒绝 (1-lending_fraction) 的申请, 用 RNGManager 保证可复现
    rng = getattr(state, "rng_manager", None)
    if rng is not None:
        rand_stream = rng.stream("credit_denials")
        denied_n = int((1.0 - lending_fraction) * len(requests))
        deny_idx = (
            set(rand_stream.choice(len(requests), size=denied_n, replace=False))
            if denied_n > 0 and len(requests) > 0
            else set()
        )
    else:
        deny_idx = set()
    for idx, (h, amt) in enumerate(requests):
        if idx in deny_idx:
            h.credit_denied_months += 1
            continue
        # 发放
        h.deposits += amt
        h.consumer_loan += amt
        h.consumer_loan_rate = loan_rate
        bank.deposits_from_hh += amt
        bank.loans_to_households += amt
        approved_total += amt


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
        distributed = 0.0
        # 按人均分配 + 把舍入残差分配给最后一人 (避免 deposit drift)
        eligible = [h for h in state.households if h.deposits > 0]
        for idx, h in enumerate(eligible):
            pay = per_hh if idx < len(eligible) - 1 else (int_hh - distributed)
            h.deposits += pay
            distributed += pay
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
        # 准备金的归宿由 P0-b 的 _bond_cycle 接管:
        # 政府用注入的现金去买私人部门的债 → 私人部门存款↓, 政府 treasury↑.
        # 因此本阶段**不**直接增 gov.treasury_deposits (避免双记账).


# ════════════════════════════════════════════════════════════
# 7b. 债券市场 (P0-b): 政府赤字经私人部门持债渠道融资 + 月度付息
# ════════════════════════════════════════════════════════════
def _bond_cycle(state: SimulationState) -> None:
    """发行新债覆盖政府赤字 + 付息.

    ⚠️ 与 Phase 2 的"赤字 100% CB 货币化"并存: 现在赤字先经 CB 货币化 (注入
    准备金), 然后立刻被本函数通过私人部门持债"倒回": 发债把等额准备金从私人
    部门抽走, 政府 treasury_deposits ↑, 私人部门 bonds ↑, 银行准备金 ↓.

    经济解读: 政府现在向私人部门借钱, 而不是直接印钞. CB 仍承担最后买家角色
    (OMO), 但默认路径走私人.

    步骤:
      A. 计算当月应发债额 = J (来自 _government_cycle 的注入)
         **以及** 当月利息支付额 I = outstanding × coupon / 12
      B. 发债: 分配给家庭 (默认 70%) + 银行 (30%),
         资金从私人部门 deposits 转到 gov.treasury_deposits.
      C. 付息: 从 gov.treasury_deposits 按持有比例分配给持有人,
         对方存款增加.
    """
    if not bool(_cfg(state, "enable_bond_market", True)):
        return
    if state.government is None or state.central_bank is None:
        return
    if state.bank is None:
        return

    bond_mkt = state.bond_market
    if bond_mkt is None:
        return

    gov = state.government
    cb = state.central_bank
    bank = state.bank

    # 票息率跟随政策利率 (避免外生硬编码)
    if state.central_bank is not None:
        bond_mkt.coupon_rate = float(state.central_bank.policy_rate)

    # ── A. 月度付息 (优先于发债: 付息后 government 才知道还需发多少新债) ──
    interest_due = bond_mkt.monthly_interest_due()
    interest_paid = 0.0
    if interest_due > 0 and bond_mkt.outstanding > 0:
        # 资金从 gov.treasury_deposits 流出 (优先) → 否则发新债补
        source = min(interest_due, gov.treasury_deposits)
        if source < interest_due:
            # treasury 不够 → 调高本期发债额 (后置覆盖)
            pass  # 在 B 步覆盖
        for hid, amt in bond_mkt.holders.items():
            pay = amt * bond_mkt.coupon_rate / 12.0
            if pay <= 0:
                continue
            # 从 gov.treasury_deposits 流出; 接收方按 hid 类型分流
            gov.treasury_deposits = max(0.0, gov.treasury_deposits - pay)
            cb.treasury_deposits = max(0.0, cb.treasury_deposits - pay)
            if hid.startswith("hh_") or hid.startswith("h_"):
                # 家庭收款: deposits ↑
                h = _find_household(state, hid)
                if h is not None:
                    h.deposits += pay
                    bank.deposits_from_hh += pay
            else:
                # 银行收款: 钱从政府 treasury 账户 → 银行准备金.
                #   cb.bank_reserves ↑pay   (CB 账上银行的存款↑)
                #   bank.reserves   ↑pay    (银行账上其在 CB 的存款↑)
                # ⚠️ 不需要单独记 bank.capital: A 增 L 不变 → capital 隐含增.
                cb.bank_reserves += pay
                bank.reserves += pay
            interest_paid += pay
    state.monthly_interest_paid = interest_paid

    # ── B. 发新债 (覆盖当月赤字 + 未补付息缺口) ──
    # 估算当月赤字 = 当月 G + TR - T (从 gov.tax_revenue 与 gov.gov_spending 推)
    primary_deficit = max(
        0.0,
        gov.gov_spending + gov.transfers - gov.tax_revenue,
    )
    unfunded_interest = max(0.0, interest_due - interest_paid)
    issuance_need = primary_deficit + unfunded_interest

    # debt brake: 不让债务超过 bond_max_debt_to_gdp × 年化 GDP
    # 但初始 gov.debt 中包含"镜像初始准备金"的"虚拟债" (SFC 中性的) —
    # 这部分不算入财政空间. 这里用 gov.debt - cb.bank_reserves 近似"净债",
    # 更准确的方法是引入独立的 "structural_debt" 字段. 当前简化为:
    #   net_debt_for_brake = gov.debt - min(gov.debt, cb.bank_reserves)
    # 即把 gov.debt 与 cb.bank_reserves 重叠的部分 (结构性货币化债) 剔除.
    annual_gdp = max(1.0, state.real_gdp * 12)
    max_net_debt = float(_cfg(state, "bond_max_debt_to_gdp", 1.5)) * annual_gdp
    net_debt = max(0.0, gov.debt - min(gov.debt, cb.bank_reserves))
    headroom = max(0.0, max_net_debt - net_debt)
    issuance_need = min(issuance_need, headroom)
    if issuance_need <= 0:
        return

    # 分配: 家庭 (按 deposits 比例) + 银行 (剩余 + 舍入残差)
    hh_share_target = float(
        _cfg(state, "bond_issuance_household_share", 0.7)
    )
    hh_total_dep = sum(h.deposits for h in state.households)
    allocations: dict[str, float] = {}
    hh_total = 0.0  # 实际计入家庭的总分配 (含 <1e-6 跳过的部分, 留给银行)
    if hh_total_dep > 0:
        target_hh = issuance_need * hh_share_target
        for h in state.households:
            w = h.deposits / hh_total_dep
            amt = w * target_hh
            if amt < 1e-6:
                # 不分配给这家 (避免微小噪声), 额计入银行承担的部分
                continue
            allocations[h.id] = amt
            h.bonds += amt
            h.deposits -= amt
            hh_total += amt
        # 镜像: 银行的家庭存款负债减 (家庭存款减少)
        bank.deposits_from_hh = max(
            0.0, bank.deposits_from_hh - hh_total
        )
    bank_amt = issuance_need - hh_total
    if bank_amt > 0:
        # 银行的"份额"直接归 CB (银行用准备金买债容易出现"准备金不足买债"
        # 引起的 phantom 资产, 这里简化为: 私人买不到的部分由 CB 持有).
        # 在更精细的实现里, 应引入银行自营账户, 与客户存款严格区分.
        allocations[cb.id] = allocations.get(cb.id, 0.0) + bank_amt
        cb.gov_bonds += bank_amt

    # 私人部门买债时, 钱从私人部门的存款"搬家"到政府 treasury 账户.
    # 镜像记账:
    cb.treasury_deposits += issuance_need
    gov.treasury_deposits += issuance_need

    # 政府 / CB 入账 (债务存量增加)
    gov.debt += issuance_need
    cb.gov_bonds += issuance_need  # CB 仍是承接方 (隐含"包销+二级转私人")

    # 更新市场簿记
    bond_mkt.issue(issuance_need, allocations)

    logger.info(
        f"  Bond issue: {issuance_need:.2f} "
        f"(prim_deficit={primary_deficit:.2f}, "
        f"unfunded_int={unfunded_interest:.2f}); "
        f"gov.debt → {gov.debt:.2f}"
    )


def _find_household(state: SimulationState, hid: str):
    for h in state.households:
        if h.id == hid:
            return h
    return None


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
# REO 清算: 把银行止赎房产卖给家庭 (所有权转移, SFC 镜像)
# ════════════════════════════════════════════════════════════
def _liquidate_reo(
    state: SimulationState,
    liquidation_discount: float,
    fire_sale: bool = False,
) -> int:
    """把银行的 REO 房产按清算折扣价卖给有存款的家庭.

    记账 (严格镜像, A = L + capital 守恒, 不动准备金 — 买方从自己在银行的
    存款付钱, 钱只是从银行的存款科目内部"流走", 银行没有真正收现金):
      银行: reo_value −V_book               (实物资产出表)
            deposits_from_hh −V_sale        (买方的存款减少, 银行负债减)
            capital +(V_sale − V_book)       (差额: 实现损益)

      CB: 不变 (无准备金变动 — 钱在银行体系内部循环)

      家庭: deposits −V_sale / housing_units +1 (买房 + 出钱)

    历史 bug: 原版把这笔记账写成 reserves↑+deposits↑, 等于凭空创造
    100 现金, 立刻被 SFC 检查捕获.
    """
    sold_total = 0
    for bank in state.banks:
        if bank.reo_properties <= 0 or bank.reo_value <= 0:
            continue
        book_per_unit = bank.reo_value / bank.reo_properties
        while bank.reo_properties > 0:
            sale_price = housing_market_sale_price(state, liquidation_discount)
            if sale_price <= 0:
                break
            buyer = pick_reo_buyer(state, sale_price)
            if buyer is None:
                # 没有买得起的家庭 → 保留在 REO, 等下月 (价格继续压)
                break
            book = book_per_unit  # 简化: 所有 REO 同价入账
            # ── 家庭 ──
            buyer.deposits -= sale_price
            buyer.housing_units += 1
            # ── 银行 (镜像) ──
            bank.deposits_from_hh = max(0.0, bank.deposits_from_hh - sale_price)
            bank.reo_value = max(0.0, bank.reo_value - book)
            bank.reo_properties -= 1
            bank.capital += sale_price - book  # 实现损益
            sold_total += 1
    return sold_total


def housing_market_sale_price(
    state: SimulationState, liquidation_discount: float,
) -> float:
    """REO 销售价 = 当前房价 × 清算折扣 (或 fire-sale 折扣).

    fire_sale=True 时额外乘 (1 − fire_sale_pressure), 即压力越大折扣越深.
    """
    if state.housing_market is None:
        return 0.0
    base = state.housing_market.price * liquidation_discount
    if state.fire_sale_pressure > 0:
        base *= 1.0 - state.fire_sale_pressure * 0.5
    return max(0.0, base)


def pick_reo_buyer(state: SimulationState, sale_price: float) -> object | None:
    """从无房家庭里挑一个买得起 sale_price 的 (用存款兜底).

    教学简化: 任何 deposits ≥ sale_price 的家庭都能买, 按存款降序取第一.
    不引入首付/信贷约束 (Phase 3+ 再加).
    """
    candidates = sorted(
        (h for h in state.households if h.deposits >= sale_price),
        key=lambda h: h.deposits,
        reverse=True,
    )
    return candidates[0] if candidates else None


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
    """构造 BS 字典并校验 SFC (金融 + 实物住房存量)."""
    bs_dict = state.build_balance_sheets()
    errors = validate_sfc(bs_dict)
    # 实物住房存量: 持有 = 家庭 + REO (BEFORE: 银行 REO 在 fire-sale 阶段直接清零)
    if state.housing_market is not None:
        total_units = state.housing_market.total_units
        if total_units > 0:
            units_hh = sum(h.housing_units for h in state.households)
            units_reo = sum(b.reo_properties for b in state.banks)
            errors.extend(
                validate_housing_stock(units_hh, units_reo, total_units)
            )
    if errors:
        logger.warning(f"SFC violations at tick {state.t}: {errors}")
        state.sfc_violations.append(errors)


# ════════════════════════════════════════════════════════════
# Phase 2: Housing + Mortgage + Interbank + Fire-sale
# ════════════════════════════════════════════════════════════


def _housing_cycle(state: SimulationState) -> None:
    """Phase 2 住房周期: 抵押月供 + 房租收入 + 房价调整 + 泡沫因子演化.

    SFC 注记 (严格分账):
    - 月供 m = 利息 + 本金
      - HH: deposits -= m, mortgage_balance -= principal
      - 银行: deposits_from_hh -= m, loans_to_households -= principal, capital += interest
      - A: loans -= principal; L: deposits -= m; capital: +(m − principal) ✓
    - 房租: 投资房收 → 租户付 (HH 内部转账, SFC 自平衡)
    """
    housing = state.housing_market
    if housing is None or state.central_bank is None:
        return

    bank = state.bank  # 主银行 (n_banks=1 时为唯一)
    if bank is None:
        return

    cb = state.central_bank

    # 1. 月供 (利息 → 银行资本; 本金 → 减少按揭余额) + 断供计数
    for h in state.households:
        if h.mortgage_balance <= 0:
            continue
        # 简化直线摊销: 利息 = balance × rate/12; 本金 = balance / 360
        interest = h.mortgage_balance * h.mortgage_rate / 12.0
        principal = h.mortgage_balance / 360.0
        due = interest + principal
        affordable = max(0.0, h.deposits)
        if affordable >= due * 0.999:
            h.mortgage_missed_payments = 0
        else:
            h.mortgage_missed_payments += 1  # 断供压力计
        payment = min(due, affordable)
        if payment <= 0:
            continue
        # 分配: 先付利息 (银行收入), 再付本金
        interest_paid = min(interest, payment)
        principal_paid = payment - interest_paid
        # 镜像记账
        h.deposits -= payment
        bank.deposits_from_hh -= payment
        h.mortgage_balance -= principal_paid
        bank.loans_to_households = max(
            0.0, bank.loans_to_households - principal_paid
        )
        bank.capital += interest_paid  # 利息是银行资本增长

    # 2. 房租收入 (HH 内部转账, SFC 自平衡: 双方均镜像银行账目)
    rental_yield = housing.rent  # 月租金
    landlords = [h for h in state.households if h.housing_units > 1]
    if landlords and rental_yield > 0:
        total_rent = sum(
            (h.housing_units - 1) * rental_yield for h in landlords
        )
        # 收方: 房东存款 ↑, bank.deposits_from_hh ↑
        for h in landlords:
            rent_received = (h.housing_units - 1) * rental_yield
            h.deposits += rent_received
            h.rental_income = rent_received
            bank.deposits_from_hh += rent_received
        # 付方: 所有租户 (housing_units == 1) 平摊, bank.deposits_from_hh ↓
        renters = [h for h in state.households if h.housing_units <= 1]
        if renters:
            per_renter = total_rent / len(renters)
            for h in renters:
                h.deposits -= per_renter
                bank.deposits_from_hh -= per_renter

    # 3. 房价调整 (租金锚定 + 利率反馈 + 泡沫因子)
    housing.revalue(policy_rate=cb.policy_rate,
                    expectations_factor=state.housing_expectations_factor)

    # 4. 泡沫因子自适应
    if len(state.housing_price_history) >= 6:
        recent_growth = (
            state.housing_price / state.housing_price_history[-6] - 1
        )
        if recent_growth > 0.05:
            state.housing_expectations_factor = min(
                1.5, state.housing_expectations_factor + 0.03
            )
        elif recent_growth < -0.05:
            state.housing_expectations_factor = max(
                0.6, state.housing_expectations_factor - 0.08
            )

    state.housing_price = housing.price
    state.housing_price_history.append(housing.price)


def _mortgage_default_check(state: SimulationState) -> None:
    """Phase 2: 房贷违约检查.

    触发: housing_value < mortgage_balance × default_ltv_threshold
          (即 LTV > 110% → 负资产 → 失业 + 高 LTV 双重打击)

    处置: 部分回收 (非凭空销毁) — 历史 bug: 原版直接 `write_off_mortgage`
    全额 + `h.housing_units = 0`, 房子消失了, 银行承担 100% 损失. 现改为:
        1. 银行以清算价 (house_value × 清算折扣) 收回房产, 入 `reo_value`
           借方 A (loans_to_hh 减 M; reo_value 加 R)        借方 L 不变
           资本: −(M − R) = −损失
        2. 房屋所有权转给银行 (从家庭搬到 REO 簿), 通过 housing_units 同步减
           家庭侧 + 增 bank.reo_properties (数量守恒)
        3. 房贷余额双边归零: bank.loans_to_hh 减 M / h.mortgage 减 M (SFC 同步)
    """
    housing = state.housing_market
    if housing is None:
        return

    bank = state.bank
    if bank is None:
        return

    missed_threshold = int(_cfg(state, "mortgage_missed_payment_limit", 3))
    liquidation_discount = float(
        _cfg(state, "mortgage_liquidation_discount", 0.70)
    )
    npl_marked = 0.0
    for h in state.households:
        if h.mortgage_balance <= 0 or h.housing_units <= 0:
            continue
        house_value = h.housing_units * housing.price
        ltv = h.mortgage_balance / house_value if house_value > 0 else float("inf")
        underwater = ltv > housing.default_ltv_threshold
        payment_stress = h.mortgage_missed_payments >= missed_threshold
        long_unemployed = (not h.employed) and h.unemployment_duration > 6
        if not (underwater and (payment_stress or long_unemployed)):
            continue

        mortgage = h.mortgage_balance
        recovery_value = house_value * liquidation_discount  # R ≤ M (默认折扣≤1)
        loss = mortgage - recovery_value                     # 银行承担的损失

        # ── 银行账本: 资产端重组, 资本减损失 ──
        bank.loans_to_households = max(
            0.0, bank.loans_to_households - mortgage
        )
        bank.reo_value += recovery_value
        bank.capital -= loss
        bank.npl_mortgages += mortgage
        bank.mark_npl(mortgage)
        bank.npl_writes_off_cumulative += loss  # 教学诊断: 累计实现损失
        npl_marked += mortgage

        # ── 家庭账本: 房贷归零, 房子所有权转银行 (数量守恒) ──
        units = h.housing_units
        h.mortgage_balance = 0.0
        h.housing_units = 0
        bank.reo_properties += units

        logger.info(
            f"  Mortgage default: HH {h.id}, LTV={ltv:.2f}, "
            f"mortgage={mortgage:.2f}, recovery={recovery_value:.2f}, "
            f"loss={loss:.2f}"
        )

    if npl_marked > 0:
        state.fire_sale_pressure = min(
            1.0, state.fire_sale_pressure + bank.reo_properties * 0.001
        )


def _interbank_cycle(state: SimulationState) -> None:
    """Phase 2 同业利息结算 (n_banks=1 时为空操作).

    简化: 每家银行支付同业负债利息, 收到同业资产利息; 净额入 capital.
    不重塑 interbank_network 结构 (敞口是给定的存量).
    """
    if state.interbank_network is None or len(state.banks) <= 1:
        return

    # 银行失败期间同业市场冻结 (对手方风险 → 停止结算), 保证聚合恒等式:
    # 若部分银行不参与, 单边确认的利息会破坏 A = L + capital.
    if any(b.is_failed for b in state.banks):
        return

    cb_rate = state.central_bank.policy_rate if state.central_bank else 0.02
    # 简化: 同业利率 = policy_rate (隐含同业市场贴近政策利率)
    for bank in state.banks:
        if bank.is_failed:
            continue
        # 收利息 (同业拆出)
        interest_in = bank.interbank_claims * cb_rate / 12.0
        bank.capital += interest_in
        # 付利息 (同业拆入)
        interest_out = bank.interbank_debt * cb_rate / 12.0
        bank.capital -= interest_out


def _fire_sale_and_failure(state: SimulationState) -> None:
    """Phase 2 fire-sale externality + 银行失败处置.

    机制 (Brunnermeier-Pedersen 2009 简化版):
    1. 银行 CAR 低于阈值 → 触发处置
    2. 失败银行:
       a. 同业债权人按 recovery_rate 承担损失 (interbank_cycle 的下一 tick 体现)
       b. 剩余资产 (主要是 gov_bonds) 在 fire-sale 压力下折价卖出
       c. REO 房产在 fire-sale 压力下推向市场, 压低房价
       d. 银行被关闭, 资本归零 (extreme)
    3. fire-sale 价格影响: 房价被压低 → 其他银行的抵押贷款价值下跌
       → 其他银行 NPL 上升 → 危机传染

    SFC 注记: 失败银行的资产清算 → 资金回笼但资本损失. 极端处置
    下, 银行 capital 可为负 (Phase 3 处置回收).
    """
    # ── 0. REO 甩卖外部性 (单/多银行模式均生效) ──
    # 房产从银行卖给家庭, 不是凭空销毁. 历史 bug: 原版 `reo_properties = 0`
    # 让房子消失 → 触发 housing_stock 校验失败.
    housing_mkt = getattr(state, "housing_market", None)
    reo_total = sum(b.reo_properties for b in state.banks)
    if housing_mkt is not None and reo_total > 0:
        impact_cfg = float(_cfg(state, "fire_sale_price_impact", 0.05))
        impact = impact_cfg * min(1.0, reo_total / max(1, housing_mkt.total_units))
        impact = min(impact, 0.20)  # 单月最多压价 20%
        housing_mkt.price *= 1.0 - impact
        if bool(_cfg(state, "enable_reo_liquidation", True)):
            liquidation_discount = float(
                _cfg(state, "mortgage_liquidation_discount", 0.70)
            )
            sold = _liquidate_reo(state, liquidation_discount, fire_sale=False)
            logger.info(
                f"  REO liquidation: {sold}/{reo_total} units sold at "
                f"{1 - liquidation_discount:.0%} discount"
            )
        else:
            logger.info(f"  REO retained: {reo_total} units (liquidation off)")
        state.fire_sale_pressure = min(
            1.0, state.fire_sale_pressure + 0.1
        )
    else:
        state.fire_sale_pressure = max(0.0, state.fire_sale_pressure - 0.02)

    if len(state.banks) <= 1:
        # 单银行模式 (n_banks=1): 仍允许银行失败/救助逻辑, 但跳过同业拆借
        # 处理 (无对手方). 救助注资本身可在单银行下生效, 用于演示 TARP 式处置.
        threshold = float(_cfg(state, "bank_failure_car_threshold", 0.04))
        bank = state.banks[0]
        if not bank.is_failed and bank.is_under_capitalized(threshold):
            bank.is_failed = True
            bank.months_since_failure = 0
            state.failed_banks.append(bank.id)
            logger.warning(
                f"Bank FAILED at t={state.t}: {bank.id}, "
                f"CAR={bank.car():.3f}, capital={bank.capital:.2f}"
            )
        # ── 救助注资 (单银行模式) ──
        if bank.is_failed and state.central_bank is not None:
            cb2 = state.central_bank
            bail_margin = float(_cfg(state, "bailout_car_margin", 0.02))
            gov_obj = state.government
            assert gov_obj is not None
            target_cap = (
                bank.car_requirement + bank.car_buffer + bail_margin
            ) * bank.total_assets()
            need = max(0.0, target_cap - bank.capital)
            if need > 1e-9:
                gov_obj.debt += need
                gov_obj.other_assets += need
                cb2.gov_bonds += need
                cb2.bank_reserves += need
                bank.reserves += need
                bank.capital += need
                logger.info(
                    f"  Bailout (single-bank): gov injected {need:.2f} "
                    f"into {bank.id}, CAR → {bank.car():.3f}"
                )
        return

    threshold = float(_cfg(state, "bank_failure_car_threshold", 0.04))
    failed_this_tick: list[str] = []

    for bank in state.banks:
        # ── 首次失败判定 (只触发一次) ──
        if not bank.is_failed and bank.is_under_capitalized(threshold):
            bank.is_failed = True
            bank.months_since_failure = 0
            failed_this_tick.append(bank.id)
            state.failed_banks.append(bank.id)
            logger.warning(
                f"Bank FAILED at t={state.t}: {bank.id}, "
                f"CAR={bank.car():.3f}, capital={bank.capital:.2f}"
            )

            # 处置: 同业敞口清算
            # 记账 (违约注销的三边镜像):
            #   - 失败银行: interbank_debt 全额注销; 以准备金偿付 recovery 部分;
            #     注销的净债务转为权益 (discharge gain)
            #   - 债权人:   interbank_claims 全额冲减; 收到 recovery 现金;
            #     损失部分侵蚀资本
            if state.interbank_network is not None:
                losses = state.interbank_network.apply_failure(
                    bank.id, recovery_rate=0.4
                )
                recovery_rate = 0.4
                total_exposure = 0.0
                for creditor_id, loss in losses.items():
                    creditor = next(
                        (b for b in state.banks if b.id == creditor_id), None
                    )
                    if creditor is None or creditor.is_failed:
                        continue
                    exposure = loss / max(1e-9, 1.0 - recovery_rate)
                    total_exposure += exposure
                    creditor.interbank_claims = max(
                        0.0, creditor.interbank_claims - exposure
                    )
                    payback = min(exposure * recovery_rate, bank.reserves)
                    creditor.reserves += payback
                    creditor.capital -= loss
                    logger.info(
                        f"  Contagion: {creditor_id} lost {loss:.2f} "
                        f"from {bank.id} failure"
                    )
                # 失败银行一侧镜像
                pay_total = min(total_exposure * recovery_rate, bank.reserves)
                bank.reserves -= pay_total
                bank.interbank_debt = max(
                    0.0, bank.interbank_debt - total_exposure
                )
                bank.capital += total_exposure - pay_total  # 债务注销收益

            # 处置 gov_bonds: 卖给 CB (流动性注入)
            # SFC: bank.deposits_from_hh? 不, 应该直接减少 bank.gov_bonds_held
            # 并增 bank.reserves (CB 购回国债)
            cb = state.central_bank
            if cb is not None and bank.gov_bonds_held > 0:
                cb.gov_bonds += bank.gov_bonds_held
                cb.bank_reserves += bank.gov_bonds_held
                bank.reserves += bank.gov_bonds_held
                bank.gov_bonds_held = 0

            # REO 房产 fire-sale: 推动房价压力
            if bank.reo_properties > 0 and state.housing_market is not None:
                # REO 越多, fire-sale 越强 (压制房价)
                reo_pressure = bank.reo_properties * 0.005
                state.housing_expectations_factor = max(
                    0.5, state.housing_expectations_factor - reo_pressure
                )
                logger.info(
                    f"  REO fire-sale: {bank.reo_properties} units, "
                    f"expectations_factor → {state.housing_expectations_factor:.2f}"
                )

        # ── 救助注资 (失败银行持续适用, TARP 式多轮) ──
        # 失败后若资本再度跌破监管线 → 政府发债注资补足.
        # 记账 (严格镜像): 政府发债 R → CB 购买 → 准备金注入银行,
        # 财政部持有对银行的股权 (other_assets).
        #   gov.debt += R / gov.other_assets += R     (政府 NW 不变)
        #   cb.gov_bonds += R / cb.bank_reserves += R (CB 恒等式保持)
        #   bank.reserves += R / bank.capital += R    (A = L + capital 保持)
        if bank.is_failed and state.central_bank is not None:
            cb2 = state.central_bank
            bail_margin = float(_cfg(state, "bailout_car_margin", 0.02))
            assets = bank.total_assets()
            gov_obj = state.government
            assert gov_obj is not None
            target_cap = (
                bank.car_requirement + bank.car_buffer + bail_margin
            ) * assets
            need = max(0.0, target_cap - bank.capital)
            if need > 1e-9:
                gov_obj.debt += need
                gov_obj.other_assets += need
                cb2.gov_bonds += need
                cb2.bank_reserves += need
                bank.reserves += need
                bank.capital += need
                logger.info(
                    f"  Bailout: gov injected {need:.2f} into {bank.id}, "
                    f"CAR → {bank.car():.3f}"
                )

            # REO 房产 fire-sale: 推动房价压力

    # Fire-sale 价格影响: 累加到房价压制
    if state.fire_sale_pressure > 0 and state.housing_market is not None:
        # 一次性价格压制: P *= (1 - impact × fire_sale_pressure)
        impact = float(_cfg(state, "fire_sale_price_impact", 0.05))
        state.housing_market.price *= (1.0 - impact * state.fire_sale_pressure)
        # 压力随时间衰减
        state.fire_sale_pressure = max(0.0, state.fire_sale_pressure * 0.85)
