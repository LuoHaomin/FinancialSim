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

import math

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


def _allocate_share(
    amount: float,
    banks: list,
    share_attr: str = "market_share",
) -> dict[str, float]:
    """Phase 3.5 PR-2: 按份额拆分到多家银行 (SFC 镜像, 残差给最后一家).

    单银行 (n_banks=1) 时快速返回全量给 banks[0].

    Parameters
    ----------
    amount : float
        待拆分总额. 负值也支持 (退款/扣款).
    banks : list[CommercialBank]
        银行列表. 顺序与 share_attr 一致; Σ share 应 ≈ 1.0.
    share_attr : str
        取每家银行该字段作为份额权重 (默认 'market_share').

    Returns
    -------
    dict[str, float]
        {bank.id: allocated_amount}. Σ == amount (浮点容差 1e-9 × scale).

    Notes
    -----
    浮点卫生 — 残差给 banks[-1], 保证 Σ 严格逐位相等. 单银行时直接返回
    全量, 不引入浮点误差.
    """
    if not banks:
        return {}
    if len(banks) == 1:
        return {banks[0].id: amount}
    if amount == 0:
        return {b.id: 0.0 for b in banks}
    out: dict[str, float] = {}
    distributed = 0.0
    last_bank = banks[-1]
    for b in banks[:-1]:
        share = max(0.0, getattr(b, share_attr, 0.0))
        v = amount * share
        out[b.id] = v
        distributed += v
    # 残差给最后一家 (SFC 逐位相等)
    out[last_bank.id] = amount - distributed
    return out


def monthly_tick(
    state: SimulationState,
    goods_market: GoodsMarket | None = None,
    labor_market: LaborMarket | None = None,
) -> None:
    """执行一个月的仿真."""
    if goods_market is None:
        goods_market = GoodsMarket()
    if labor_market is None:
        # 校准 2026-08 重大修复: 此处此前的裸构造忽略 SimConfig 全部
        # 劳动参数 (离职率/匹配效率/调整速度/工资频率...), 生产路径
        # 实际运行的永远是类默认值 — from_config 只有测试在调用.
        labor_market = LaborMarket.from_config(state.config)

    logger.debug(f"=== Tick {state.t} start ===")

    _apply_events(state)
    _cb_decisions(state)
    # 生产率趋势增长 (月度复利): 无此通道时 real GDP 永久冻结, 经济退化为静态稳态.
    prod_g = float(_cfg(state, "productivity_growth_monthly", 0.0))
    if prod_g:
        for f in state.firms:
            if not f.is_bankrupt:
                f.productivity *= 1.0 + prod_g
    labor_market.clear(state)
    for f in state.firms:
        f.last_sales = 0.0
        f.last_demand = 0.0  # 本月需求意向清零 (消费 + 政府 G 写入)
    _supply_chain_cycle(state)            # Week E-M1: IO 中间品采购 (默认关闭)
    # 生产先于消费 (校准 2026-08): 本月产出必须先入库, 家庭/政府才有货可买.
    # 此前消费在 update_inventory 之前执行, 月初货架 ≈ 上月末残余库存,
    # 长期缺货配给 → 销售额被压低 → 劳动需求塌缩 (高失业陷阱).
    goods_market.update_inventory(state)
    _consumer_credit_cycle(state)         # Phase 3 前置 P0-a: 消费贷申请 + 配给 + 还款
    _household_consumption(state)
    goods_market.clear(state)  # 定价基于销售后的库存状态
    if _cfg(state, "calvo_price_prob", 0.0):
        _maybe_calvo_pricing(state, goods_market)
    _bank_cycle(state)
    _housing_cycle(state)                 # Phase 2: 抵押 + 房租 + 价格
    _government_cycle(state)
    # 发薪在收入进账之后 (校准 2026-08): 此前工资先于全部货款支付,
    # 企业月初现金恒 < 工资单 → 每月永久透支营运资本贷款, 本金永不
    # 摊还 + 利息资本化 → 每 ~200 月技术性破产一次. 时序上等价于
    # "月末发薪", 实际经济中企业以当月销售回款支付工资.
    _pay_wages(state)
    _bond_cycle(state)                    # Phase 3 前置 P0-b: 发债 + 付息
    _firm_dividend_cycle(state)           # Week B: 企业现金 → 家庭股东
    _firm_capital_cycle(state)
    _default_resolution(state)            # Phase 1+: 违约检测 + 处置 + 恢复
    _mortgage_default_check(state)        # Phase 2: 房贷违约 → 银行 NPL
    _interbank_cycle(state)               # Phase 2: 同业利息 (n_banks>1 时生效)
    _fire_sale_and_failure(state)         # Phase 2: fire-sale + 失败处置
    _stock_market_cycle(state)            # Week C: BH 股票市场 (默认关闭)
    _household_rebalance(state)           # Week C M2: risk_tolerance 组合再平衡
    _asset_manager_cycle(state)           # Week D: 申购赎回 + 被动抛售 (先跑, 其抛售价格冲击计入 IB 对账)
    _investment_bank_cycle(state)         # Week D: VaR 去杠杆 + repo (默认关闭)
    _reconcile_nbfi(state)                # Week D: 收盘资本对账 (浮点卫生)
    _aggregate_macros(state)
    # Week B: 销售/需求历史入档 (劳动需求决策的滞后输入; 保留 13 个月窗口)
    for f in state.firms:
        sh = list(f.sales_history) if f.sales_history is not None else []
        sh.append(f.last_sales)
        f.sales_history = sh[-13:]
        dh = list(f.demand_history) if f.demand_history is not None else []
        dh.append(f.last_demand)
        f.demand_history = dh[-13:]
    _validate_sfc(state)

    state.t += 1


# ════════════════════════════════════════════════════════════
# 1. 事件系统: 在 CB 决策之前注入参数冲击
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
# 3. 工资支付 (Phase 3: 按雇主归属逐企业支付)
# ════════════════════════════════════════════════════════════
def _pay_wages(state: SimulationState) -> None:
    """各企业给自己的员工发工资, 钱从 firm.deposits 转到 hh.deposits.

    Phase 3.5 行为化: 在发薪前, 先按生产规模补足工作资本缺口 (working capital).
    规模 = monthly_sales * working_capital_factor, 受存款上限约束, 不足部分借.
    这让 firm.debt 与产出挂钩 → 贷款利息随 GDP 顺周期 → 银行资本顺周期.

    Phase 3.5 PR-3a: 多银行真拆分 — 工资流按 firm/HH 的 home_bank_id 镜像到
    具体银行 (而非全走主银行). 单银行 (n_banks=1) 维持主银行语义快路径.

    SFC (双侧镜像, 行内对冲零净额):
      firm.deposits  ↑WC      firm.debt ↑WC
      bank.deposits_from_firms ↑WC  bank.loans_to_firms ↑WC
    """
    bank = state.bank
    assert bank is not None

    employed_hh = [h for h in state.households if h.employed]
    if not employed_hh:
        return

    by_employer: dict[str | None, list] = {}
    for h in employed_hh:
        by_employer.setdefault(h.employer_id, []).append(h)

    # ── Phase 3.5 PR-3a: 多银行时按 home_bank_id 查表 ──
    n_banks = len(state.banks)
    multi_bank = n_banks > 1
    bank_by_id: dict[str, object] = (
        {b.id: b for b in state.banks} if multi_bank else {}
    )

    # ── Phase 3.5: 工作资本按产出规模补充 (生产-债务挂钩) ──
    # 目标运营现金 = monthly_sales × factor; 不足时按缺口借新钱.
    # 在 GDP 上行期 (sales↑) → 借更多 → 利息支出↑ → 银行利息收入↑;
    # GDP 下行期 (sales↓) → 还本压力 (按 repayment_speed 缩) → 银行利息↓
    # → 银行资本自然顺周期, 无需单独 NPL 通道.
    wc_factor = float(_cfg(state, "firm_working_capital_factor", 0.20))
    max_growth = float(_cfg(state, "firm_max_loan_growth_factor", 0.20))
    for firm in state.firms:
        if firm.is_bankrupt or wc_factor <= 0:
            continue
        # 工作资本目标 = 当月工资单 × factor — 与就业规模直接挂钩,
        # 经济上行就业↑→ 工资单↑ → 借款↑ → 利息↑ → 银行资本顺周期.
        # 失业期就业↓ → 工资单↓ → 还本缩债 → 银行利息↓.
        labor_cost = firm.wage_offered * max(1, firm.employees)
        target_wc = wc_factor * labor_cost
        gap = max(0.0, target_wc - firm.deposits)
        if gap > 1e-9:
            # 借款上限: 单月新增借款 ≤ max(20% × 当前债务, 1 月工资单) — 二者取大,
            # 保证即使 debt=0 时也能启动借款 (历史 bug: 初始 debt=0 时上限=0 死锁).
            max_new_debt = max(firm.debt * max_growth, labor_cost * max_growth)
            borrow = min(gap, max_new_debt)
            if borrow > 1e-9:
                firm.debt += borrow
                firm.deposits += borrow
                # 多银行: firm 借款入其 home_bank
                f_bank = (
                    bank_by_id[firm.home_bank_id] if multi_bank
                    else bank
                )
                f_bank.loans_to_firms += borrow  # type: ignore[attr-defined]
                f_bank.deposits_from_firms += borrow  # type: ignore[attr-defined]

    for firm in state.firms:
        group = by_employer.get(firm.id)
        if not group:
            continue
        total_wages = len(group) * firm.wage_offered

        # 多银行: firm 的 home_bank
        f_bank = bank_by_id[firm.home_bank_id] if multi_bank else bank

        # 存款不足时向银行借款补足 (债务资本化, 不动资本)
        if firm.deposits < total_wages:
            shortfall = total_wages - firm.deposits
            firm.debt += shortfall
            f_bank.loans_to_firms += shortfall  # type: ignore[attr-defined]
            f_bank.deposits_from_firms += shortfall  # type: ignore[attr-defined]
            firm.deposits += shortfall

        firm.deposits -= total_wages
        f_bank.deposits_from_firms -= total_wages  # type: ignore[attr-defined]

        wage_per_hh = total_wages / len(group)
        for h in group:
            h.income = wage_per_hh
            h.deposits += wage_per_hh
            # 多银行: 工资按 HH 的 home_bank 镜像 (HH 可在不同银行开户)
            if multi_bank:
                h_bank = bank_by_id[h.home_bank_id]  # type: ignore[index]
                h_bank.deposits_from_hh += wage_per_hh  # type: ignore[attr-defined]
        # 单银行: 在循环外加总 (SFC 镜像, 一次到 banks[0])
        if not multi_bank:
            bank.deposits_from_hh += total_wages


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
# 4. 家庭消费 (Phase 3: 需求按部门份额流向各企业)
# ════════════════════════════════════════════════════════════
def _distribute_to_firms(
    state: SimulationState,
    amount: float,
    shares: dict[str, float],
) -> list[tuple[object, float]]:
    """把 amount 按部门份额分到企业, 舍入残差给最后一家.

    返回 [(firm, 分配额)]; 分配额之和与 amount 逐位一致.
    """
    sector_firms: dict[str, list] = {}
    for f in state.firms:
        sector_firms.setdefault(f.sector, []).append(f)
    alloc: list[tuple[object, float]] = []
    if not state.firms or amount <= 0:
        return alloc
    pairs: list[tuple[object, float]] = []
    for sector, share in shares.items():
        group = sector_firms.get(sector)
        if not group:
            continue
        per = amount * share / len(group)
        for f in group:
            pairs.append((f, per))
    if not pairs:
        # 配置份额没覆盖任何现有部门 → 全给第一家企业 (兜底)
        return [(state.firms[0], amount)]
    distributed = sum(v for _, v in pairs)
    last_f, last_v = pairs[-1]
    pairs[-1] = (last_f, last_v + (amount - distributed))  # 残差吸收
    return pairs


def _household_consumption(state: SimulationState) -> None:
    """HH 决定消费; 各部门按份额承接需求, 受库存约束限量成交.

    Week B 微观修正: 库存不足时**不成交的部分退回家中存款**
    (此前是"没货也收钱"的幻影购买). 未成交需求记入 firm.last_demand,
    作为劳动市场扩张的信号 — 否则"少雇人→供给不足→销售萎缩"死循环.

    Phase 3.5 PR-3b: 多银行时按 HH/firm 的 home_bank 镜像:
      - HH 支付的金额从 HH 的 home_bank.deposits_from_hh 扣 (按 HH 分摊)
      - 企业收到的金额加到 firm 的 home_bank.deposits_from_firms
    单银行维持主银行语义快路径.
    """
    bank = state.bank
    assert bank is not None

    cfg = state.config
    shares = (
        cfg.normalized_demand_shares()
        if cfg is not None and hasattr(cfg, "normalized_demand_shares")
        else {}
    )

    # ── PR-3b: 多银行 home_bank 查表 ──
    n_banks = len(state.banks)
    multi_bank = n_banks > 1
    bank_by_id: dict[str, object] = (
        {b.id: b for b in state.banks} if multi_bank else {}
    )

    # 阶段 1: HH 扣款 + 按 home_bank 累计 HH 支付
    total_intent = 0.0
    hh_paid_by_bank: dict[str, float] = {}
    for h in state.households:
        c = min(h.decide_consumption(), h.deposits)
        c = max(c, 0.0)
        h.deposits -= c          # 先全额扣款
        total_intent += c
        if multi_bank:
            bid = h.home_bank_id
            hh_paid_by_bank[bid] = hh_paid_by_bank.get(bid, 0.0) + c

    paid_total = 0.0
    if total_intent > 0:
        # 阶段 2: 把总需求分到企业, 按企业价格/库存限量成交
        for f, req in _distribute_to_firms(state, total_intent, shares):
            units = min(req / max(f.price, 1e-9), f.inventory)
            served = units * f.price
            f.deposits += served
            f.inventory = max(0.0, f.inventory - units)
            f.last_sales += served
            f.last_demand += req
            paid_total += served
            # 企业的 home_bank 加 deposits_from_firms (SFC 镜像)
            if multi_bank:
                f_bank = bank_by_id[f.home_bank_id]
                f_bank.deposits_from_firms += served  # type: ignore[attr-defined]
        # 未成交部分退款 (按户均摊, 残差给最后一户)
        refund = total_intent - paid_total
        if refund > 1e-9:
            n = len(state.households)
            distributed = 0.0
            for i, h in enumerate(state.households):
                pay = refund / n if i < n - 1 else refund - distributed
                h.deposits += pay
                distributed += pay
            # 退款按 HH 的 home_bank 加回 (多银行); 单银行加 banks[0]
            if multi_bank:
                for hid, hh_obj in enumerate(state.households):
                    # 残差处理: 按户均摊后, 每户的退款应回到自己 home_bank.
                    # 简化: 把全部 refund 按 hh_paid_by_bank 份额加回 (近似)
                    # (理想是 per-HH refund per home_bank — 见 docs)
                    pass
                # 简化路径: per-bank 等比例分配 refund
                n_banks_active = len(hh_paid_by_bank)
                if n_banks_active > 0:
                    per_bank_refund = refund / n_banks_active
                    for bid in hh_paid_by_bank:
                        bank_by_id[bid].deposits_from_hh += per_bank_refund  # type: ignore[attr-defined]
                    # 残差给 banks[0]
                    bank_by_id[sim := list(bank_by_id.values())[0].id].deposits_from_hh += refund - per_bank_refund * n_banks_active  # type: ignore[attr-defined]
            else:
                bank.deposits_from_hh += refund

        # 阶段 3: HH 的 home_bank 扣 deposits_from_hh
        if multi_bank:
            for bid, paid_amt in hh_paid_by_bank.items():
                bank_by_id[bid].deposits_from_hh -= paid_amt  # type: ignore[attr-defined]
            # 残差给 banks[0] (SFC 镜像)
            residual = total_intent - sum(hh_paid_by_bank.values())
            if abs(residual) > 1e-9:
                bank_by_id[list(bank_by_id.values())[0].id].deposits_from_hh -= residual  # type: ignore[attr-defined]
        else:
            bank.deposits_from_hh -= total_intent
            bank.deposits_from_firms += paid_total
    state.last_month_sales = paid_total


# ════════════════════════════════════════════════════════════
# 5b. 卡尔沃定价 (可选, calvo_price_prob > 0 时启用)
# ════════════════════════════════════════════════════════════
def _maybe_calvo_pricing(
    state: SimulationState,
    goods_market: GoodsMarket,
) -> None:
    """以概率 θ 把价格调到目标加成价 (库存规则已在 clear() 生效).

    每家企业独立抽签; 抽签使用 RNGManager 的 'pricing' 流;
    没有 manager 时跳过.
    """
    mgr = getattr(state, "rng_manager", None)
    if mgr is None or not state.firms:
        return
    rng = mgr.stream("pricing")
    for firm in state.firms:
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

    Phase 3.5 PR-3d: 多银行时每家银行独立 set_rates + 利息流按 firm/HH 的
    home_bank 镜像. 单银行维持主银行语义快路径.
    """
    bank = state.bank
    cb = state.central_bank
    assert bank is not None
    assert cb is not None

    n_banks = len(state.banks)
    multi_bank = n_banks > 1
    bank_by_id: dict[str, object] = (
        {b.id: b for b in state.banks} if multi_bank else {}
    )

    # 多银行时每家银行独立 set_rates; 单银行直接复用 banks[0]
    loan_rate, deposit_rate = bank.set_rates(cb.policy_rate)
    bank_rates: dict[str, tuple[float, float]] = {}
    if multi_bank:
        for b in state.banks:
            lr, dr = b.set_rates(cb.policy_rate)
            bank_rates[b.id] = (lr, dr)

    # ── 贷款利息 (逐企业: 有存款付现金, 没存款资本化) ──
    for firm in state.firms:
        if multi_bank:
            lr, _dr = bank_rates[firm.home_bank_id]
            f_bank = bank_by_id[firm.home_bank_id]
        else:
            lr = loan_rate
            f_bank = bank
        loan_interest = firm.debt * lr / 12.0
        if loan_interest <= 0:
            continue
        if firm.deposits >= loan_interest:
            firm.deposits -= loan_interest
            f_bank.deposits_from_firms -= loan_interest  # type: ignore[attr-defined]
            f_bank.book_loan_interest_income(loan_interest)
        else:
            firm.debt += loan_interest
            f_bank.loans_to_firms += loan_interest  # type: ignore[attr-defined]
            f_bank.book_loan_interest_income(loan_interest)

    # ── 本金摊还 (PR-3d 多银行: 还本走 firm 的 home_bank) ──
    repay_speed = float(_cfg(state, "firm_loan_repayment_speed", 0.30))
    if repay_speed > 0:
        for firm in state.firms:
            if firm.is_bankrupt or firm.debt <= 1e-9:
                continue
            floor = firm.wage_offered * max(1, firm.employees)
            surplus = firm.deposits - floor
            repay = min(firm.debt, max(0.0, surplus) * repay_speed)
            if repay <= 1e-9:
                continue
            firm.deposits -= repay
            firm.debt = max(0.0, firm.debt - repay)
            if multi_bank:
                f_bank = bank_by_id[firm.home_bank_id]
            else:
                f_bank = bank
            f_bank.loans_to_firms = max(  # type: ignore[attr-defined]
                0.0, f_bank.loans_to_firms - repay  # type: ignore[attr-defined]
            )
            f_bank.deposits_from_firms -= repay  # type: ignore[attr-defined]

    # ── 存款利息 (PR-3d 多银行: 每家银行独立付其 HH/firm 存款利息) ──
    int_hh_total = 0.0
    int_firm_total = 0.0
    if multi_bank:
        for b in state.banks:
            _lr, dr = bank_rates[b.id]
            int_hh = b.deposits_from_hh * dr / 12.0
            firm_dep_at_bank = sum(
                f.deposits for f in state.firms
                if f.home_bank_id == b.id
            )
            int_firm = firm_dep_at_bank * dr / 12.0
            int_hh_total += int_hh
            int_firm_total += int_firm
            if int_hh > 0:
                # 按 deposit 比例分给这家银行的 HH (按 home_bank_id)
                hh_at_bank = [h for h in state.households if h.home_bank_id == b.id and h.deposits > 0]
                if hh_at_bank:
                    per_hh = int_hh / len(hh_at_bank)
                    distributed = 0.0
                    for idx, h in enumerate(hh_at_bank):
                        pay = per_hh if idx < len(hh_at_bank) - 1 else (int_hh - distributed)
                        h.deposits += pay
                        distributed += pay
                    b.deposits_from_hh += int_hh
            if int_firm > 0 and firm_dep_at_bank > 0:
                firms_at_bank = [f for f in state.firms if f.home_bank_id == b.id and f.deposits > 0]
                if firms_at_bank:
                    distributed = 0.0
                    for idx, f in enumerate(firms_at_bank):
                        if idx < len(firms_at_bank) - 1:
                            pay = int_firm * f.deposits / firm_dep_at_bank
                            distributed += pay
                        else:
                            pay = int_firm - distributed
                        f.deposits += pay
                    b.deposits_from_firms += int_firm
            b.book_deposit_interest_expense(int_hh + int_firm)
    else:
        int_hh = bank.deposits_from_hh * deposit_rate / 12.0
        firm_dep_total = sum(f.deposits for f in state.firms)
        int_firm = firm_dep_total * deposit_rate / 12.0
        int_hh_total = int_hh
        int_firm_total = int_firm
        if int_hh > 0:
            per_hh = int_hh / max(1, sum(1 for h in state.households if h.deposits > 0))
            distributed = 0.0
            eligible = [h for h in state.households if h.deposits > 0]
            for idx, h in enumerate(eligible):
                pay = per_hh if idx < len(eligible) - 1 else (int_hh - distributed)
                h.deposits += pay
                distributed += pay
            bank.deposits_from_hh += int_hh
        if int_firm > 0 and firm_dep_total > 0:
            eligible_firms = [f for f in state.firms if f.deposits > 0]
            distributed = 0.0
            for idx, f in enumerate(eligible_firms):
                if idx < len(eligible_firms) - 1:
                    pay = int_firm * f.deposits / firm_dep_total
                    distributed += pay
                else:
                    pay = int_firm - distributed
                f.deposits += pay
            bank.deposits_from_firms += int_firm
        bank.book_deposit_interest_expense(int_hh + int_firm)

    # ── 央行准备金付息 (IOR, floor system; 校准 2026-08) ──
    # PR-3d: 多银行时每家银行独立计 IOR, 残差给 banks[0]
    if bool(_cfg(state, "enable_interest_on_reserves", True)):
        if multi_bank:
            total_ior = 0.0
            for b in state.banks:
                reserve_base = max(
                    0.0,
                    b.deposits_from_hh + b.deposits_from_firms
                    + getattr(b, "deposits_from_nbfi", 0.0)
                    - b.loans_to_firms - b.loans_to_households,
                )
                ior_payment = reserve_base * float(cb.policy_rate) / 12.0
                if ior_payment > 1e-9:
                    b.reserves += ior_payment
                    b.capital += ior_payment
                    total_ior += ior_payment
            if total_ior > 1e-9:
                cb.bank_reserves += total_ior
                cb.capital -= total_ior
        else:
            reserve_base = max(
                0.0,
                bank.deposits_from_hh + bank.deposits_from_firms
                + getattr(bank, "deposits_from_nbfi", 0.0)
                - bank.loans_to_firms - bank.loans_to_households,
            )
            ior_payment = reserve_base * float(cb.policy_rate) / 12.0
            if ior_payment > 1e-9:
                bank.reserves += ior_payment
                bank.capital += ior_payment
                cb.bank_reserves += ior_payment
                cb.capital -= ior_payment


# ════════════════════════════════════════════════════════════
# 6b. 银行分红 (Phase 3 稳态修复): 超额资本按比例分给家庭股东
# ════════════════════════════════════════════════════════════
def _bank_dividend_cycle(state: SimulationState) -> None:
    """银行超额资本 → 家庭股东分红 (账面转移, 无现金流动).

    之前 bank.capital 只能从贷款利息收入单调上升, 没有出口 → 稳态失衡.
    Phase 3 修复: 当 CAR > bank_dividend_car_target 时, 把超额资本按
    bank_dividend_payout 比例"以股票分红"形式分给家庭 — 资本直接转换为
    HH 存款, 不涉及准备金/现金流动.

    SFC 注记 (账面转移, 双重记账):
      bank.capital ↓D
      bank.deposits_from_hh ↑D       (HH 的存款负债增加 — 资本退出银行的
                                     体现: 以前是 capital, 现在是 deposits)
      h.deposits ↑D
    净效果: bank.A 不变, bank.L ↑D, bank.cap ↓D → A = L + cap 保持 ✓.

    PR-3f: 多银行时每家银行的分红按 HH 的 home_bank 加 deposits_from_hh.
    """
    if not bool(_cfg(state, "enable_bank_dividends", True)):
        return
    if state.bank is None:
        return
    bank = state.bank
    n_banks = len(state.banks)
    multi_bank = n_banks > 1
    bank_by_id: dict[str, object] = (
        {b.id: b for b in state.banks} if multi_bank else {}
    )
    payout_ratio = float(_cfg(state, "bank_dividend_payout", 0.6))
    target_car = float(_cfg(state, "bank_dividend_car_target", 0.10))
    # PR-3f: per-bank 累计分红(各银行自有 capital → 自己的 deposits_from_hh)
    dividend_by_bank: dict[str, float] = {}
    for b in state.banks:
        car = b.car()
        if car <= target_car or car == float("inf"):
            continue
        excess = b.capital - target_car * b.total_assets()
        if excess <= 1e-9:
            continue
        payout = payout_ratio * excess
        # 银行侧: capital 减, deposits_from_hh 增 (账面转移, 无现金流动)
        b.capital -= payout
        dividend_by_bank[b.id] = dividend_by_bank.get(b.id, 0.0) + payout
    if not dividend_by_bank or sum(dividend_by_bank.values()) <= 0:
        return
    # 把分红按 HH 存款比例分给家庭, 同时按 HH 的 home_bank 加各银行 deposits_from_hh
    hh_total_dep = sum(h.deposits for h in state.households)
    if hh_total_dep <= 0:
        return
    if multi_bank:
        # per-bank 分红先按 share 比例切到 HH (按 HH 的 home_bank 累计)
        for h in state.households:
            share = h.deposits / hh_total_dep
            h.deposits += share * sum(dividend_by_bank.values())
        for bid, amt in dividend_by_bank.items():
            bank_by_id[bid].deposits_from_hh += amt  # type: ignore[attr-defined]
    else:
        for h in state.households:
            share = h.deposits / hh_total_dep
            pay = share * sum(dividend_by_bank.values())
            h.deposits += pay
        bank.deposits_from_hh += sum(dividend_by_bank.values())


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
    cb = state.central_bank
    assert gov is not None
    assert bank is not None
    assert cb is not None

    cfg = state.config
    shares = (
        cfg.normalized_demand_shares()
        if cfg is not None and hasattr(cfg, "normalized_demand_shares")
        else {}
    )

    income_tax_rate_base = float(_cfg(state, "income_tax_rate", 0.25))
    income_tax_rate = _effective_income_tax_rate(state, income_tax_rate_base)
    corp_tax_rate = float(_cfg(state, "corp_tax_rate", 0.21))

    # ── PR-3c: 多银行 home_bank 查表 ──
    n_banks = len(state.banks)
    multi_bank = n_banks > 1
    bank_by_id: dict[str, object] = (
        {b.id: b for b in state.banks} if multi_bank else {}
    )

    # ── 收入税 (从工资中预扣; 同时下调 h.income 为税后口径) ──
    total_income_tax = 0.0
    income_tax_by_bank: dict[str, float] = {}
    for h in state.households:
        if h.employed and h.income > 0:
            t = h.income * income_tax_rate
            h.deposits -= t
            h.income -= t
            total_income_tax += t
            if multi_bank:
                bid = h.home_bank_id
                income_tax_by_bank[bid] = income_tax_by_bank.get(bid, 0.0) + t
    if multi_bank:
        for bid, amt in income_tax_by_bank.items():
            bank_by_id[bid].deposits_from_hh -= amt  # type: ignore[attr-defined]
        residual = total_income_tax - sum(income_tax_by_bank.values())
        if abs(residual) > 1e-9:
            bank_by_id[list(bank_by_id.values())[0].id].deposits_from_hh -= residual  # type: ignore[attr-defined]
    else:
        bank.deposits_from_hh -= total_income_tax

    # ── 公司税 (逐企业) ──
    corp_tax_total = 0.0
    corp_tax_by_bank: dict[str, float] = {}
    for f in state.firms:
        t = max(0.0, f.profit()) * corp_tax_rate
        t = min(t, f.deposits)
        f.deposits -= t
        corp_tax_total += t
        if multi_bank:
            bid = f.home_bank_id
            corp_tax_by_bank[bid] = corp_tax_by_bank.get(bid, 0.0) + t
    if multi_bank:
        for bid, amt in corp_tax_by_bank.items():
            bank_by_id[bid].deposits_from_firms -= amt  # type: ignore[attr-defined]
        residual = corp_tax_total - sum(corp_tax_by_bank.values())
        if abs(residual) > 1e-9:
            bank_by_id[list(bank_by_id.values())[0].id].deposits_from_firms -= residual  # type: ignore[attr-defined]
    else:
        bank.deposits_from_firms -= corp_tax_total
    gov.tax_revenue = total_income_tax + corp_tax_total

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
        benefits_by_bank: dict[str, float] = {}
        for h in unemployed:
            h.deposits += per_hh
            h.income = per_hh
            if multi_bank:
                bid = h.home_bank_id
                benefits_by_bank[bid] = benefits_by_bank.get(bid, 0.0) + per_hh
        if multi_bank:
            for bid, amt in benefits_by_bank.items():
                bank_by_id[bid].deposits_from_hh += amt  # type: ignore[attr-defined]
            residual = total_benefits - sum(benefits_by_bank.values())
            if abs(residual) > 1e-9:
                bank_by_id[list(bank_by_id.values())[0].id].deposits_from_hh += residual  # type: ignore[attr-defined]
        else:
            bank.deposits_from_hh += total_benefits
    if g_spending > 0:
        # Week B: 政府购买改为真实市场采购 — 抽库存 + 计入企业销售额.
        # 此前 G 是"凭空注资" (只加存款不扣库存), 需求基数因此缺失 G 的
        # 一块, 动态劳动需求会让就业自我塌缩 (实测单部门 24 月失业 85%).
        # 库存不足时按可成交量收账 (未成交部分政府不付款).
        served_total = 0.0
        g_by_bank: dict[str, float] = {}
        for f, req in _distribute_to_firms(state, g_spending, shares):
            units = min(req / max(f.price, 1e-9), f.inventory)  # 金额→数量
            served = units * f.price
            f.deposits += served
            f.inventory = max(0.0, f.inventory - units)
            f.last_sales += served              # 金额口径 (与消费一致)
            f.last_demand += req
            served_total += served
            if multi_bank:
                bid = f.home_bank_id
                g_by_bank[bid] = g_by_bank.get(bid, 0.0) + served
        if multi_bank:
            for bid, amt in g_by_bank.items():
                bank_by_id[bid].deposits_from_firms += amt  # type: ignore[attr-defined]
            residual = served_total - sum(g_by_bank.values())
            if abs(residual) > 1e-9:
                bank_by_id[list(bank_by_id.values())[0].id].deposits_from_firms += residual  # type: ignore[attr-defined]
        else:
            bank.deposits_from_firms += served_total
        # 赤字融资只覆盖实际支出
        g_spending = served_total

    gov.transfers = total_benefits
    gov.gov_spending = g_spending

    # ── 赤字融资: 发行国债给 CB, 换成准备金注入银行体系 ──
    # PR-3c: 多银行时,准备金按 market_share 分配到各银行(残差给 banks[0])
    injection = g_spending + total_benefits - gov.tax_revenue
    if abs(injection) > 0:
        gov.debt += injection            # 发行(+)/回购(−)
        cb.gov_bonds += injection        # CB 承接
        cb.bank_reserves += injection    # 准备金注入/回笼
        if multi_bank:
            for b in state.banks:
                share_amt = injection * b.market_share
                b.reserves += share_amt
            state.banks[0].reserves += injection - sum(
                injection * b.market_share for b in state.banks
            )
        else:
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
    if not bool(_cfg(state, "enable_bond_market", False)):
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
# 7c. 企业分红 (Week B): 盈利部门囤积的现金回流家庭股东
# ════════════════════════════════════════════════════════════
def _firm_dividend_cycle(state: SimulationState) -> None:
    """超过"2 个月工资单"缓冲的企业现金, 按 payout 比例分给家庭.

    经济含义: 家庭是企业部门的最终所有者. 若无此出口, 需求份额占优的
    部门会无限囤积购买力 → 总需求塌缩 → 结构性失业 (实测多部门 u≈25%).

    记账 (银行负债科目间转移, 总量不变):
      firm.deposits ↓D / bank.deposits_from_firms ↓D
      h.deposits   ↑D / bank.deposits_from_hh   ↑D     (Σpay 逐位一致)
    """
    if not bool(_cfg(state, "enable_firm_dividends", True)):
        return
    bank = state.bank
    if bank is None or not state.firms:
        return
    payout_ratio = float(_cfg(state, "firm_dividend_payout", 0.40))

    total_div = 0.0
    allocs: list[tuple[object, float]] = []
    for f in state.firms:
        buffer = 2.0 * f.employees * f.wage_offered
        excess = max(0.0, f.deposits - buffer)
        div = min(payout_ratio * excess, f.deposits)
        if div <= 1e-9:
            continue
        allocs.append((f, div))
        total_div += div
    if total_div <= 0:
        return

    # 分配权重: 股市启用时按持股 (股东语义含企业股东 M3),
    # 否则回退按存款比例. 残差给最后一个收款人.
    mkt = getattr(state, "stock_market", None)
    use_shares = (
        bool(_cfg(state, "enable_stock_market", False))
        and mkt is not None
        and sum(h.stock_units for h in state.households) > 0
    )
    firm_shareholders: list[tuple[object, float]] = []
    if use_shares and bool(_cfg(state, "enable_cross_holdings", False)):
        for f in state.firms:
            if f.shares_held_by_firms > 0:
                firm_shareholders.append((f, f.shares_held_by_firms))
    hh_weights = [h.stock_units for h in state.households]
    weights_sum = (
        sum(hh_weights) + sum(w for _, w in firm_shareholders)
        if use_shares
        else sum(h.deposits for h in state.households)
    )
    if weights_sum <= 0:
        return
    bank2 = state.bank
    assert bank2 is not None
    div_to_firms_total = 0.0

    def _pay_firm_shareholders(amount: float) -> None:
        """把 amount 按持股分给企业股东 (残差给最后一家)."""
        nonlocal div_to_firms_total
        if amount <= 1e-9 or not firm_shareholders:
            return
        total_w = sum(w for _, w in firm_shareholders)
        paid = 0.0
        n = len(firm_shareholders)
        for i, (f, w) in enumerate(firm_shareholders):
            amt = (
                amount * w / total_w
                if i < n - 1
                else amount - paid
            )
            f.deposits += amt
            f.dividend_received_from_firms = amt
            paid += amt
        bank2.deposits_from_firms += amount
        div_to_firms_total += amount

    total_div_hh = total_div
    if use_shares and firm_shareholders:
        firms_weight = sum(w for _, w in firm_shareholders)
        share_of_total = firms_weight / (
            sum(hh_weights) + firms_weight
        )
        total_div_hh = total_div * (1.0 - share_of_total)
        _pay_firm_shareholders(total_div * share_of_total)

    distributed = 0.0
    eligible = [
        (h, (h.stock_units if use_shares else h.deposits))
        for h in state.households
    ]
    weights_sum = (
        sum(w for _, w in eligible)
        if use_shares
        else sum(w for _, w in eligible)
    )
    if weights_sum <= 0:
        return
    n = len(eligible)
    for i, (h, w) in enumerate(eligible):
        pay = (
            total_div_hh * w / weights_sum
            if i < n - 1
            else total_div_hh - distributed
        )
        h.deposits += pay
        distributed += pay
    state.last_month_dividends = total_div  # 股息锚含企业部分 (总量口径)

    paid = 0.0
    for i, (f, div) in enumerate(allocs):
        deduct = div if i < len(allocs) - 1 else (total_div - paid)
        f.deposits -= deduct
        paid += deduct
    bank.deposits_from_firms -= total_div            # 付款方扣减 (全额)
    bank.deposits_from_hh += total_div_hh            # 家庭股东收款
    # 企业股东部分已由 _pay_firm_shareholders 内镜像入 deposits_from_firms


# ════════════════════════════════════════════════════════════
# 8. 企业资本循环: 折旧 + 投资 (Phase 3 Week A: 投资实流化)
# ════════════════════════════════════════════════════════════
def _firm_capital_cycle(state: SimulationState) -> None:
    """K ← K(1−δ) 后执行加速器投资.

    投资实流化 (存在资本品部门时):
      采购价值 V = min(意愿 I, 资本品部门库存) — 资本形成受真实产能约束.
      记账 (买卖双方 + 银行负债侧逐位镜像):
        买方: deposits −V / capital +V
        卖方: inventory −V / deposits +V / last_sales += V (资本品营收)
        银行: deposits_from_firms 净额 0 (买方减 = 卖方增)
        验收恒等式: Σ采购支出 == Σ资本品部门投资营收 (state.last_month_investment)

    无资本品部门时 (legacy 单部门): 维持 Phase 0 的"留存利润实物化"
    简化 (deposits 不动, capital += I), 见 Firm.invest 文档.

    库存按名义市值记账: 交易以价值 V 结转, 不拆数量×单价 (文档化约定).
    """
    from financial_sim.config import CAPITAL_GOODS_SECTORS

    dep_rate = float(_cfg(state, "depreciation_rate", 0.01))
    inv_sens = float(_cfg(state, "investment_sensitivity", 0.5))
    for f in state.firms:
        f.depreciation_rate = dep_rate
        f.investment_sensitivity = inv_sens

    capital_sellers = [
        f for f in state.firms
        if f.sector in CAPITAL_GOODS_SECTORS and not f.is_bankrupt
    ]

    total_investment = 0.0
    for buyer in state.firms:
        if buyer.is_bankrupt:
            continue
        buyer.depreciate()
        want = buyer.decide_investment()
        if want <= 0:
            continue

        if not capital_sellers:
            # legacy 路径: 无资本品部门 → 聚合实物化 (不动存款, SFC 中性)
            buyer.invest(want)
            total_investment += want
            continue

        # 实流化路径: 从资本品企业真实采购 (受库存产能约束)
        remaining = min(want, sum(s.inventory for s in capital_sellers))
        remaining = min(remaining, buyer.deposits)  # 审慎上限 (decide_investment 已含, 双保险)
        for seller in capital_sellers:
            if remaining <= 1e-9:
                break
            v = min(remaining, seller.inventory)
            if v <= 0:
                continue
            # ── 记账 (同为主银行账内, 净额为零的镜像) ──
            buyer.deposits -= v
            bank = state.bank
            assert bank is not None
            bank.deposits_from_firms -= v
            seller.deposits += v
            bank.deposits_from_firms += v
            # 实物 + 资本形成
            seller.inventory = max(0.0, seller.inventory - v)
            seller.last_sales += v     # 资本品营收
            buyer.capital += v
            total_investment += v
            remaining -= v

    state.last_month_investment = total_investment


# ════════════════════════════════════════════════════════════
# ============================================================
# 8c. 股票市场 (Week C): Brock-Hommes 价格发现 + 家庭持仓结算
# ============================================================
def _stock_market_cycle(state: SimulationState) -> None:
    """跑一个月的股票子步循环, 并把净单位流结算成家庭存款/持仓.

    SFC 注记:
    - 二级市场内部转移在家庭间轧平, 聚合存款不变 → 只结算**净流**
    - 净买入 Q: 存款 ↓Q×p; 净卖出反向 (镜像 bank.deposits_from_hh)
    - 审慎上限: 单月净申购 ≤ 家庭存款 × stock_order_fraction
    """
    mkt = state.stock_market
    if not bool(_cfg(state, "enable_stock_market", False)):
        return
    if mkt is None or getattr(mkt, "supply_units", 0.0) <= 0:
        return

    mgr = getattr(state, "rng_manager", None)
    if mgr is None:
        return
    rng = mgr.stream("stocks")

    div_per_share = (
        state.last_month_dividends / mkt.supply_units
        if mkt.supply_units > 0 else 0.0
    )
    result = mkt.step_month(div_per_share * 12.0, rng, state)

    net_units = float(result.get("net_flow_units", 0.0))
    if abs(net_units) < 1e-9:
        return
    price = mkt.price
    held_total = sum(h.stock_units for h in state.households)
    hh_dep = sum(h.deposits for h in state.households)
    cap = float(_cfg(state, "stock_order_fraction", 0.10))
    cost = abs(net_units) * price
    if net_units > 0 and cost > hh_dep * cap:
        net_units = (hh_dep * cap) / price        # 审慎削减净申购
    if held_total > 0 and abs(net_units) > held_total:
        net_units = math.copysign(held_total, net_units)

    settled = 0.0
    n = len(state.households)
    for i, h in enumerate(state.households):
        share_u = (
            net_units * h.stock_units / held_total
            if held_total > 0 and i < n - 1
            else net_units - settled              # 残差给最后一户
        )
        h.stock_units = max(0.0, h.stock_units + share_u)
        h.deposits -= share_u * price             # 买+扣款 / 卖+回款
        settled += share_u
    bank = state.bank
    assert bank is not None
    bank.deposits_from_hh -= net_units * price    # 聚合镜像


# ════════════════════════════════════════════════════════════
# 8d. 家庭组合再平衡 (Week C M2): 存款 ↔ 股票 按 risk_tolerance
# ════════════════════════════════════════════════════════════
def _household_rebalance(state: SimulationState) -> None:
    """各家庭向目标股票权重缓慢迁移: w* = base + coeff × risk_tolerance.

    供给守恒的过户语义 (SFC 关键约定):
      家庭间的买卖互相配对成交 — 总股数与聚合存款均不变,
      只是存款在买卖双方之间转移 + 股票过户.
      未配对的超额需求/供给当期不成交 (下期价格调整后再试).
    """
    if not bool(_cfg(state, "enable_stock_market", False)):
        return
    mkt = state.stock_market
    if mkt is None or getattr(mkt, "supply_units", 0.0) <= 0:
        return
    price = max(mkt.price, 1e-9)
    base = float(_cfg(state, "portfolio_weight_base", 0.05))
    tol_coeff = float(_cfg(state, "portfolio_weight_tol_coeff", 0.40))
    speed = min(1.0, float(_cfg(state, "portfolio_rebalance_speed", 0.20)))

    buyers: list[tuple[object, float]] = []   # (hh, 意愿买入金额>0)
    sellers: list[tuple[object, float]] = []  # (hh, 意愿卖出金额>0)
    for h in state.households:
        wealth = h.deposits + h.stock_units * price
        if wealth <= 0:
            continue
        w_star = min(0.90, max(0.0, base + tol_coeff * h.risk_tolerance))
        w_cur = h.stock_units * price / wealth
        want = speed * (w_star - w_cur) * wealth
        if want > 1e-9:
            buyers.append((h, min(want, h.deposits)))   # 不透支存款
        elif want < -1e-9:
            sellers.append((h, min(-want, h.stock_units * price)))

    total_buy = sum(v for _, v in buyers)
    total_sell = sum(v for _, v in sellers)
    matched = min(total_buy, total_sell)
    if matched < 1e-9:
        return

    # 等额配对: 买方按意愿比例分配 matched 金额, 卖方对称
    done_buy = 0.0
    for i, (h, want) in enumerate(buyers):
        pay = (
            matched * want / total_buy
            if i < len(buyers) - 1
            else matched - done_buy     # 残差给最后一家
        )
        pay = min(pay, h.deposits)
        h.deposits -= pay
        h.stock_units += pay / price
        done_buy += pay
    done_sell = 0.0
    for i, (h, want) in enumerate(sellers):
        receive = (
            matched * want / total_sell
            if i < len(sellers) - 1
            else matched - done_sell
        )
        sell_units = receive / price
        sell_units = min(sell_units, h.stock_units)
        h.stock_units -= sell_units
        h.deposits += sell_units * price
        done_sell += sell_units * price



def _cross_trade_with_households(
    state: SimulationState,
    nbfi_buys_value: float,
    price: float,
) -> None:
    """NBFI 与家庭部门的指数交易清算 (单位 + 现金 双镜像).

    nbfi_buys_value > 0: NBFI 买入 — 家庭出让单位并收到等额存款;
    < 0: NBFI 卖出 — 家庭受让单位并支付存款.
    银行两侧科目同额对冲 (nbfi 与 hh), 恒等式零净影响.
    调用方需在银行账上同步 nbfi ±value 与 hh ∓value... 即:
        bank.deposits_from_nbfi ±= |value|
        bank.deposits_from_hh   ∓= |value|
    本函数负责家庭分户的逐位精确划转, 并返回**家庭端实际成交金额**
    (受家庭持仓/存款上限截断时可能小于名义额); 调用方必须以返回值做
    银行科目镜像, 不能用名义额.
    """
    held_total = sum(h.stock_units for h in state.households)
    dep_total = sum(h.deposits for h in state.households)
    units_total = abs(nbfi_buys_value) / max(price, 1e-9)
    done_u = 0.0
    done_v = 0.0
    if nbfi_buys_value > 0:
        # 家庭卖单位收现金: 按持仓比例卖, 上限 = 各户持仓
        denom = max(held_total, 1e-9)
        allocs = [
            min(units_total * h.stock_units / denom,
                float(h.stock_units))
            for h in state.households
        ]
        deficit = units_total - sum(allocs)
        if deficit > 1e-9:
            return 0.0                        # 家庭吸收能力不足 → 零成交
        for i, h in enumerate(state.households):
            u = allocs[i]
            v = min(u * price, max(0.0, h.deposits) + u * price)
            v = u * price                     # 卖出必收款 (现金不受限)
            h.stock_units -= u
            h.deposits += v
            done_u += u
            done_v += v
    else:
        # 家庭买单位付现金: 按存款比例买, 上限 = 各户存款可负担量
        denom = max(dep_total, 1e-9)
        allocs = [
            min(units_total * h.stock_units / denom,
                h.deposits / max(price, 1e-9))
            for h in state.households
        ]
        deficit = units_total - sum(allocs)
        if deficit > 1e-9:
            return 0.0
        for i, h in enumerate(state.households):
            u = allocs[i]
            cost = min(u * price, h.deposits)
            h.stock_units += u
            h.deposits -= cost
            done_u += u
            done_v += cost
    return done_v


def _shift_units_household_to(state: SimulationState, units: float) -> None:
    """把 units 单位指数在家庭部门按持仓比例划转 (NBFI 交易对手方).

    units>0: 家庭整体受让; units<0: 家庭整体出让.
    对价现金的科目镜像由调用方完成 (hh ↔ nbfi 等额对冲).
    """
    held_total = sum(h.stock_units for h in state.households)
    if held_total <= 1e-9 or abs(units) < 1e-12:
        return
    n = len(state.households)
    done = 0.0
    for i, h in enumerate(state.households):
        share_u = (
            units * h.stock_units / held_total
            if i < n - 1
            else units - done
        )
        h.stock_units = max(0.0, h.stock_units + share_u)
        done += share_u


# ════════════════════════════════════════════════════════════
# Week D-1: 投行周期 — VaR 目标仓位 / repo 融资 / 强制去杠杆
# ════════════════════════════════════════════════════════════
def _investment_bank_cycle(state: SimulationState) -> None:
    """投行以资本为底仓加杠杆持有指数; 波动率↑ → 目标杠杆↓ → 卖出.

    SFC 注记 (镜像与做市商池语义一致):
      - NBFI 交易对手方是市场池 → 变动镜像 bank.deposits_from_nbfi
      - 回购 = 银行向投行放贷: bank.deposits_from_nbfi ↑X ↔
        ib.deposits ↑X, ib.repo_debt ↑X
      - 利息 (policy+spread): 现金付则双向减; 拖欠则资本化并同时记
        银行利息收入 (book_loan_interest_income)
    """
    ib = state.investment_bank
    if not bool(_cfg(state, "enable_investment_bank", False)) or ib is None:
        return
    mkt = state.stock_market
    if mkt is None or getattr(mkt, "supply_units", 0.0) <= 0:
        return
    price = max(mkt.price, 1e-9)
    bank = state.bank
    cb = state.central_bank
    assert bank is not None
    assert cb is not None

    hist = list(ib.return_history) if ib.return_history else []
    ret = (
        mkt.price_history[-1] / mkt.price_history[-2] - 1.0
        if len(mkt.price_history) >= 2 else 0.0
    )
    ib.update_vol(ret)
    hist.append(ret)
    ib.return_history = hist[-13:]

    # 1. 调仓到 VaR 目标仓位; 对手方 = 家庭部门 (银行内科目对冲零净额):
    #    IB 买 C 元: nbfi_dep −C ↔ hh_dep +C (家庭让渡单位); 卖出反向.
    target_value = ib.desired_position(price)
    want_units = target_value / price - ib.stock_units
    max_units = (
        float(_cfg(state, "stock_order_fraction", 0.15))
        * 12 * ib.capital / price
    )
    du = max(-max_units, min(max_units, want_units))
    if abs(du) > 1e-9:
        value = abs(du) * price
        if du > 0:
            pay = min(value, ib.deposits)
            if pay > 1e-9:
                filled = _cross_trade_with_households(state, pay, price)
                pay = min(pay, filled)
                ib.deposits -= pay
                ib.stock_units += pay / price
                bank.deposits_from_nbfi -= pay
                bank.deposits_from_hh += pay
        else:
            nominal_cash = abs(du) * price
            filled = _cross_trade_with_households(
                state, -nominal_cash, price
            )
            if filled <= 1e-9:
                pass                          # 家庭吸收不足 → 本期不调仓卖出
            else:
                sell = filled / price
                cash = filled
                ib.stock_units -= sell
                ib.deposits += cash
                bank.deposits_from_nbfi += cash
                bank.deposits_from_hh -= cash

    # 2. 回购融资: 把持仓超出资本的部分用 repo 支撑 (受 leverage_max 限制)
    pos_val = ib.position_value(price)
    repo_target = min(
        max(0.0, pos_val - ib.capital),
        float(_cfg(state, "ib_leverage_max", 5.0)) * ib.capital,
    )
    d_repo = repo_target - ib.repo_debt
    if d_repo > 1e-9:
        ib.repo_debt += d_repo
        ib.deposits += d_repo
        bank.deposits_from_nbfi += d_repo       # 银行放贷创造存款 (负债)
        bank.repo_claims += d_repo              # 银行的回购债权 (资产) ✓
    elif d_repo < -1e-9:
        repay = min(-d_repo, ib.repo_debt, ib.deposits)
        ib.repo_debt -= repay
        ib.deposits -= repay
        bank.deposits_from_nbfi -= repay
        bank.repo_claims = max(0.0, bank.repo_claims - repay)

    # 3. 回购利息
    rate = cb.policy_rate + float(_cfg(state, "ib_repo_spread", 0.01))
    interest = ib.repo_debt * rate / 12.0
    if interest > 1e-12:
        paid_cash = min(interest, ib.deposits)
        ib.deposits -= paid_cash
        capitalized = interest - paid_cash
        ib.repo_debt += capitalized
        bank.deposits_from_nbfi -= paid_cash
        bank.book_loan_interest_income(interest)
        bank.repo_claims += capitalized          # 资本化利息同步加债权

    # 资本对账 (浮点卫生): 市值变动已体现在资产端, 由恒等式给出
    implied_capital = ib.deposits + ib.position_value(price) - ib.repo_debt
    drift = implied_capital - ib.capital
    if abs(drift) < 1e-6:
        ib.capital = implied_capital
    else:
        logger.warning(
            f"IB capital drift {drift:.4f} at t={state.t}; 已对账修复"
        )
        ib.capital = implied_capital

    # 5. 强平: margin 缺口 → 卖出持仓还回购直到比率恢复或卖无可卖
    gap = ib.margin_call_gap(price)
    if gap > 1e-9 and ib.stock_units > 0:
        ib.is_deleveraging = True
        impact = float(_cfg(state, "fire_sale_price_impact", 0.05))
        while True:
            assets = ib.deposits + ib.position_value(price)
            req = float(_cfg(state, "ib_margin_requirement", 0.08)) * assets
            need = max(0.0, req - ib.capital)
            if need <= 1e-9 or ib.stock_units <= 1e-12:
                break
            units_needed = min(ib.stock_units, need / price * 1.5 + 1e-9)
            cash = units_needed * price
            ib.stock_units -= units_needed
            ib.deposits += cash
            bank.deposits_from_nbfi += cash
            # fire-sale 价格冲击 (Brunnermeier-Pedersen: 抛售压价)
            press = impact * min(1.0, units_needed /
                                 max(mkt.depth_scale(), 1e-9))
            mkt.price *= 1.0 - min(0.10, press)
            price = max(mkt.price, 1e-9)
            # 还回购 (强平期加速还款)
            repay = min(ib.repo_debt, ib.deposits)
            ib.repo_debt -= repay
            ib.deposits -= repay
            bank.deposits_from_nbfi -= repay
            bank.repo_claims = max(0.0, bank.repo_claims - repay)
        implied = ib.deposits + ib.position_value(price) - ib.repo_debt
        ib.capital = implied


# ════════════════════════════════════════════════════════════
# Week D-2: 资管周期 — 动量申购 / 业绩赎回 / 被动抛售
# ════════════════════════════════════════════════════════════
def _asset_manager_cycle(state: SimulationState) -> None:
    """基金赎回螺旋骨架: 净值下跌 → 赎回 → 被动卖出压价 → 更多赎回.

    本里程碑 AM 直接与市场池交互 (家庭端资金流接入留下一里程碑).
    记账同投行: 全部镜像 bank.deposits_from_nbfi.
    """
    am = state.asset_manager
    if not bool(_cfg(state, "enable_asset_manager", False)) or am is None:
        return
    mkt = state.stock_market
    if mkt is None or getattr(mkt, "supply_units", 0.0) <= 0:
        return
    if am.fund_units_outstanding <= 1e-9:
        return
    price = max(mkt.price, 1e-9)
    bank = state.bank
    assert bank is not None

    nav_prev = (
        am.nav_history[-1] if am.nav_history else am.nav(price)
    )
    nav_ret = am.nav(price) / max(nav_prev, 1e-9) - 1.0
    nav_now = am.nav(max(mkt.price, 1e-9))

    # ── D-M2: 家庭端申赎清算 (闭环赎回螺旋) ──
    # 赎回: 业绩越差赎回越多 → AM 现金不足时被动抛售(压价) → 净值再跌.
    base_rr = float(_cfg(state, "am_base_redemption_rate", 0.02))
    sens = float(_cfg(state, "am_redemption_sensitivity", 1.5))
    redeem_rate = min(0.30, base_rr + sens * max(0.0, -nav_ret))
    redeem_value = min(
        redeem_rate * am.fund_units_outstanding * nav_now,
        max(0.0, am.deposits)
        + max(0.0, am.stock_units) * price,
    )
    if redeem_value > 1e-9:
        from_cash = min(redeem_value, am.deposits)
        deficit = redeem_value - from_cash
        if deficit > 1e-9:
            # 现金池不足 → 被动卖出 (fire-sale 压价 → 正反馈通道)
            impact = float(_cfg(state, "fire_sale_price_impact", 0.05))
            nominal = deficit
            filled = _cross_trade_with_households(state, -nominal, price)
            sell_units = filled / price
            am.stock_units -= sell_units
            am.deposits += filled
            bank.deposits_from_nbfi += filled
            bank.deposits_from_hh -= filled
            press = impact * min(
                1.0, sell_units / max(mkt.depth_scale(), 1e-9)
            )
            mkt.price *= 1.0 - min(0.10, press)
        # ⚠️ 实际可支付额 = 现金池余额 (from_cash + 强平实收).
        # 用名义 redeem_value 支付会造成无对手方的付款 → SFC 违反.
        payable = max(0.0, am.deposits)
        # 向家庭按份额比例支付赎回款 (nbfi→hh 科目转移, 恒等式零净额)
        fund_total = sum(h.fund_units for h in state.households)
        if payable > 1e-9 and fund_total > 1e-9:
            n_hhs = len(state.households)
            paid_total = 0.0
            for i, h in enumerate(state.households):
                amt = (
                    payable * h.fund_units / fund_total
                    if i < n_hhs - 1
                    else payable - paid_total
                )
                redeemed_u = (
                    amt / nav_now if nav_now > 1e-9 else h.fund_units
                )
                redeemed_u = min(redeemed_u, h.fund_units)
                h.fund_units -= redeemed_u
                h.deposits += amt
                paid_total += amt
            am.deposits -= payable
            am.fund_units_outstanding = max(
                0.0, am.fund_units_outstanding - paid_total / nav_now
            )
            bank.deposits_from_nbfi -= payable
            bank.deposits_from_hh += payable
        am.redemption_rate = redeem_rate

    # 申购: 净值上涨动量期小幅流入 (家庭按存款比例支付认购款)
    momentum_sub = (
        float(_cfg(state, "am_subscription_momentum", 0.01))
        if nav_ret > 0 else 0.0
    )
    if momentum_sub > 0:
        sub_value = min(
            momentum_sub * sum(h.deposits for h in state.households),
            sum(h.deposits for h in state.households),
        )
        if sub_value > 1e-9:
            n_hhs = len(state.households)
            dep_pool = sum(h.deposits for h in state.households)
            collected = 0.0
            for i, h in enumerate(state.households):
                amt = (
                    sub_value * h.deposits / dep_pool
                    if i < n_hhs - 1
                    else sub_value - collected
                )
                amt = min(amt, h.deposits)
                h.deposits -= amt
                h.fund_units += amt / nav_now
                collected += amt
            am.deposits += collected
            am.fund_units_outstanding += collected / nav_now
            bank.deposits_from_hh -= collected
            bank.deposits_from_nbfi += collected

    # 风险预算再平衡余核: 现金缓冲超配时缓慢回归市场 (对手方=家庭)
    cash_buffer_target = min(
        0.60,
        base_rr + sens * max(0.0, -nav_ret),
    )
    total_assets = max(am.assets_value(max(mkt.price, 1e-9)), 1e-9)
    current_buffer = am.deposits / total_assets
    gap_value = (cash_buffer_target - current_buffer) * total_assets

    if gap_value > 1e-9 and am.stock_units > 1e-9:
        # 风控性减仓 (被动抛售): fire-sale 压价 → 正反馈通道.
        # 对手方 = 家庭部门 (银行内科目对冲).
        impact = float(_cfg(state, "fire_sale_price_impact", 0.05))
        nominal = min(gap_value, am.stock_units * price)
        filled = _cross_trade_with_households(state, -nominal, price)
        sell_units = filled / price
        am.stock_units -= sell_units
        am.deposits += filled
        bank.deposits_from_nbfi += filled
        bank.deposits_from_hh -= filled
        press = impact * min(1.0, sell_units / max(mkt.depth_scale(), 1e-9))
        mkt.price *= 1.0 - min(0.10, press)
    elif gap_value < -1e-9:
        # 现金缓冲超配 → 缓慢回归市场 (买回, 每月至多一半缺口)
        buy_value = min(-gap_value * 0.5, am.deposits)
        if buy_value > 1e-9:
            filled = _cross_trade_with_households(state, buy_value, price)
            buy_value = min(buy_value, filled)
            am.deposits -= buy_value
            am.stock_units += buy_value / price
            bank.deposits_from_nbfi -= buy_value
            bank.deposits_from_hh += buy_value
    am.redemption_rate = cash_buffer_target  # 教学诊断口径: 目标缓冲率

    nav_hist = list(am.nav_history) if am.nav_history else []
    nav_hist.append(am.nav(max(mkt.price, 1e-9)))
    am.nav_history = nav_hist[-13:]


# ════════════════════════════════════════════════════════════
# Week D: NBFI 收盘资本对账
# ════════════════════════════════════════════════════════════
def _reconcile_nbfi(state: SimulationState) -> None:
    """收盘时把 IB 的资本按恒等式重标 (价格已定, 浮点卫生口径).

    经科目镜像校验器拦截真正的记账 bug (drift 大于浮点尾差会告警).
    """
    ib = getattr(state, "investment_bank", None)
    if ib is None:
        return
    price = max(getattr(state.stock_market, "price", 0.0) or 0.0, 1e-9)
    implied = ib.deposits + ib.stock_units * price - ib.repo_debt
    if abs(implied - ib.capital) > 1e-6 * max(1.0, abs(ib.capital)):
        logger.warning(f"IB capital reconcile drift {implied-ib.capital:.4f}")
    ib.capital = implied



# ════════════════════════════════════════════════════════════
# Week E-M1: 供应链 IO — 上游(能源)中间品采购 + 断供传导
# ════════════════════════════════════════════════════════════
def _supply_chain_cycle(state: SimulationState) -> None:
    """下游企业按 IO 份额向能源部门采购中间品.

    断供传导链: 能源产出不足 → 购买受库存约束 → input_utilization<1
    → 下游 production() 按比例折减 (CES/线性统一在 A_eff 生效).

    记账 (买卖双方镜像):
      买方 deposits ↓V / 银行 deposits_from_firms ↓V
      卖方 deposits ↑V / 银行 deposits_from_firms ↑V   (行内对冲零净额)
      卖方 inventory ↓V / last_sales ↑V                (实物出库+营收)
    """
    if not bool(_cfg(state, "enable_supply_chain", False)):
        return
    bank = state.bank
    if bank is None or not state.firms:
        return
    cfg = getattr(state, "config", None)
    shares = getattr(cfg, "io_input_shares", {}) if cfg else {}
    default_share = float(getattr(cfg, "io_input_share_default", 0.08)) \
        if cfg else 0.08
    suppliers = [
        f for f in state.firms
        if not f.is_bankrupt and (
            "energy" in f.sector.lower() or f.sector == "energy"
        )
    ]
    for f in state.firms:
        f.input_utilization = 1.0          # 每期重置
    if not suppliers:
        return

    warn_ratio = float(getattr(cfg, "io_capacity_warning_ratio", 0.95)) \
        if cfg else 0.95
    for buyer in state.firms:
        if buyer.is_bankrupt or buyer is None or buyer in suppliers:
            continue
        share = float(shares.get(buyer.sector, default_share))
        desired = share * buyer.production() * max(buyer.price, 1e-9)
        if desired <= 1e-9:
            continue
        remaining = min(desired, max(buyer.deposits, 0.0))
        received = 0.0
        for sup in suppliers:
            if remaining <= 1e-9:
                break
            units = min(remaining / max(sup.price, 1e-9), sup.inventory)  # 金额→数量
            v = units * sup.price
            if v <= 1e-9:
                continue
            # ── 镜像记账 ──
            buyer.deposits -= v
            bank.deposits_from_firms -= v
            sup.deposits += v
            bank.deposits_from_firms += v
            sup.inventory = max(0.0, sup.inventory - units)
            sup.last_sales += v
            received += v
            remaining -= v
        util = min(1.0, received / desired) if desired > 1e-9 else 1.0
        buyer.input_utilization = util
        if util < warn_ratio:
            logger.info(
                f"  supply-chain: {buyer.id} 输入满足率 {util:.2f} "
                f"(断供传导 → 本月产出折减)"
            )
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
    """Phase 1+ 简化违约流程 (Phase 3: 逐企业).

    检测 → 处置 → 银行核销 → 计时 → (cool-down 后) 再注资.
    SFC 注记: declare_bankruptcy 已把 firm.debt 减为 0, 此时银行核销贷款与
    资本同步下降, 资产-负债恒等式保持.

    PR-3f: 多银行时违约走 firm 的 home_bank; recapitalize 同.
    """
    if not bool(_cfg(state, "enable_default", True)):
        return

    bank = state.bank
    if bank is None or not state.firms:
        return

    n_banks = len(state.banks)
    multi_bank = n_banks > 1
    bank_by_id: dict[str, object] = (
        {b.id: b for b in state.banks} if multi_bank else {}
    )

    cooldown = int(_cfg(state, "default_cooldown_months", DEFAULT_COOLDOWN_MONTHS))
    recap_amount = float(_cfg(state, "recovery_capital_amount", 100.0))

    for firm in state.firms:
        if multi_bank:
            f_bank = bank_by_id[firm.home_bank_id]
        else:
            f_bank = bank
        # ── 1. 检测违约 (净资产 < 阈值 且 未破产) ──
        if not firm.is_bankrupt and firm.is_default():
            logger.info(f"Default detected at t={state.t}: {firm.id} equity={firm.equity():.2f}")
            detail = firm.declare_bankruptcy()

            # 历史记账 bug (Phase 3 Week A 发现并修复): declare_bankruptcy 把
            # 清算回收 R 记入 firm.deposits 却无银行对手方 → 每次 +R 的
            # 企业存款幽灵增量被 SFC 捕获. 镜像: 银行接收等额清算资产.
            #   bank: seized_assets ↑R / deposits_from_firms ↑R  (A=L+cap 保持)
            if detail["recovered"] > 0:
                f_bank.seized_assets += detail["recovered"]  # type: ignore[attr-defined]
                f_bank.deposits_from_firms += detail["recovered"]  # type: ignore[attr-defined]

            # 银行镜像 (SFC 同步):
            if detail["debt_repaid"] > 0:
                f_bank.deposits_from_firms = max(  # type: ignore[attr-defined]
                    0.0, f_bank.deposits_from_firms - detail["debt_repaid"]  # type: ignore[attr-defined]
                )
                f_bank.loans_to_firms = max(  # type: ignore[attr-defined]
                    0.0, f_bank.loans_to_firms - detail["debt_repaid"]  # type: ignore[attr-defined]
                )

            # 未偿还部分: 银行核销 (loans 减, capital 减)
            if detail["debt_unpaid"] > 0:
                f_bank.mark_npl(detail["debt_unpaid"])  # type: ignore[attr-defined]
                written = f_bank.write_off_loan(detail["debt_unpaid"])  # type: ignore[attr-defined]
                logger.info(
                    f"  Bank wrote off {written:.2f}, "
                    f"CAR now {f_bank.car():.3f}"  # type: ignore[attr-defined]
                )

            # 解雇该企业员工 (联动 HH 失业状态)
            for h in state.households:
                if h.employed and h.employer_id == firm.id:
                    h.lose_job()

        # ── 2. 破产计时 + 恢复注资 ──
        if firm.is_bankrupt:
            firm.tick_bankruptcy()
            if firm.months_bankrupt >= cooldown:
                # 银行新贷款注入资本: A 与 L 同步增加
                f_bank.loans_to_firms += recap_amount  # type: ignore[attr-defined]
                f_bank.deposits_from_firms += recap_amount  # type: ignore[attr-defined]
                firm.recapitalize(recap_amount)
                logger.info(
                    f"Recapitalized {firm.id} at t={state.t}: "
                    f"capital={recap_amount:.2f}"
                )


# ════════════════════════════════════════════════════════════
# 9. 宏观聚合
# ════════════════════════════════════════════════════════════
def _aggregate_macros(state: SimulationState) -> None:
    """计算并存储宏观变量: GDP、失业、通胀、预期、永久收入."""
    state.real_gdp = state.total_output()
    # 名义产出 = Σ Y_i × P_i; 价格水平 = 产出加权平均价 (单企业时与 legacy 一致)
    nominal_gdp = sum(f.production() * f.price for f in state.firms)
    state.nominal_gdp = nominal_gdp

    # ⚠️ 时序约定 (与 Phase 1 一致, 勿改): 通胀先用**上一期**的价格水平算,
    # 之后才把本期加权价写入 price_level/history.
    # 若反过来, 首月环比 (+60% 年化) 会立刻打给 Taylor rule, 政策利率瞬时
    # 尖峰会把房价推离基本面锚, baseline 会掉进抵押违约的脆弱盆地 (实测).
    _update_inflation(state)
    if state.real_gdp > 0:
        new_price_level = nominal_gdp / state.real_gdp
    elif state.firms:
        new_price_level = state.firms[0].price
    else:
        new_price_level = state.price_level
    state.unemployment_rate = state.unemployment_rate_calc()
    state.output_gap = (
        (state.real_gdp - state.potential_gdp) / state.potential_gdp
        if state.potential_gdp > 0
        else 0.0
    )

    _update_inflation(state)

    # 价格水平进入历史: 先 append 本期值, 再覆盖 price_level
    # (通胀已用上一期值计算完毕, 见上方时序约定注释)
    state.price_level_history.append(new_price_level)
    state.price_level = new_price_level

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

    n_banks = len(state.banks)
    multi_bank = n_banks > 1
    bank_by_id: dict[str, object] = (
        {b.id: b for b in state.banks} if multi_bank else {}
    )

    # 1. 月供 (利息 → 银行资本; 本金 → 减少按揭余额) + 断供计数
    # PR-3e: 多银行时月供走 HH 的 home_bank (mortgage 持有方)
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
        if multi_bank:
            m_bank = bank_by_id[h.home_bank_id]
        else:
            m_bank = bank
        m_bank.deposits_from_hh -= payment  # type: ignore[attr-defined]
        h.mortgage_balance -= principal_paid
        m_bank.loans_to_households = max(  # type: ignore[attr-defined]
            0.0, m_bank.loans_to_households - principal_paid  # type: ignore[attr-defined]
        )
        m_bank.capital += interest_paid  # type: ignore[attr-defined]

    # 2. 房租收入 (HH 内部转账, SFC 自平衡: 双方均镜像银行账目)
    rental_yield = housing.rent  # 月租金
    landlords = [h for h in state.households if h.housing_units > 1]
    if landlords and rental_yield > 0:
        total_rent = sum(
            (h.housing_units - 1) * rental_yield for h in landlords
        )
        # 收方: 房东存款 ↑, bank.deposits_from_hh ↑
        rent_by_bank: dict[str, float] = {}
        for h in landlords:
            rent_received = (h.housing_units - 1) * rental_yield
            h.deposits += rent_received
            h.rental_income = rent_received
            if multi_bank:
                bid = h.home_bank_id
                rent_by_bank[bid] = rent_by_bank.get(bid, 0.0) + rent_received
        if multi_bank:
            for bid, amt in rent_by_bank.items():
                bank_by_id[bid].deposits_from_hh += amt  # type: ignore[attr-defined]
            residual = total_rent - sum(rent_by_bank.values())
            if abs(residual) > 1e-9:
                bank_by_id[list(bank_by_id.values())[0].id].deposits_from_hh += residual  # type: ignore[attr-defined]
        else:
            bank.deposits_from_hh += total_rent
        # 付方: 所有租户 (housing_units == 1) 平摊, bank.deposits_from_hh ↓
        renters = [h for h in state.households if h.housing_units <= 1]
        if renters:
            per_renter = total_rent / len(renters)
            rent_pay_by_bank: dict[str, float] = {}
            for h in renters:
                h.deposits -= per_renter
                if multi_bank:
                    bid = h.home_bank_id
                    rent_pay_by_bank[bid] = rent_pay_by_bank.get(bid, 0.0) + per_renter
            if multi_bank:
                for bid, amt in rent_pay_by_bank.items():
                    bank_by_id[bid].deposits_from_hh -= amt  # type: ignore[attr-defined]
                residual = total_rent - sum(rent_pay_by_bank.values())
                if abs(residual) > 1e-9:
                    bank_by_id[list(bank_by_id.values())[0].id].deposits_from_hh -= residual  # type: ignore[attr-defined]
            else:
                bank.deposits_from_hh -= total_rent

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
    """Phase 3.5 行为化房贷违约检查.

    触发 (任一即可):
      A. 经典 (Phase 2): underwater AND (断供≥N 月 OR 长期失业>6 月)
      B. 行为化 (Phase 3.5): 连续 K 个月 underwater → 强制违约 (negative-equity trap)
         即使家庭存款仍能月供, 负资产心理压力 + 理性再配置 (理性违约模型) 也会触发.
         K 默认 6 月 → 慢但确定性; 房价崩 50%+ 后 ~3-4 月内出现首批违约级联.

    处置: 部分回收 (非凭空销毁) — 历史 bug: 原版直接 `write_off_mortgage`
    全额 + `h.housing_units = 0`, 房子消失了, 银行承担 100% 损失. 现改为:
        1. 银行以清算价 (house_value × 清算折扣) 收回房产, 入 `reo_value`
           借方 A (loans_to_hh 减 M; reo_value 加 R)        借方 L 不变
           资本: −(M − R) = −损失
        2. 房屋所有权转给银行 (从家庭搬到 REO 簿), 通过 housing_units 同步减
           家庭侧 + 增 bank.reo_properties (数量守恒)
        3. 房贷余额双边归零: bank.loans_to_hh 减 M / h.mortgage 减 M (SFC 同步)

    SFC 注记: 行为化触发不引入新账户, 只增加 months_underwater 计数.
    """
    housing = state.housing_market
    if housing is None:
        return

    bank = state.bank
    if bank is None:
        return

    n_banks = len(state.banks)
    multi_bank = n_banks > 1
    bank_by_id: dict[str, object] = (
        {b.id: b for b in state.banks} if multi_bank else {}
    )

    missed_threshold = int(_cfg(state, "mortgage_missed_payment_limit", 3))
    underwater_months_threshold = int(
        _cfg(state, "mortgage_underwater_months_threshold", 6)
    )
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

        # 维护 underwater 计数 (仅在房贷户中累计)
        if underwater:
            h.months_underwater += 1
        else:
            h.months_underwater = 0

        payment_stress = h.mortgage_missed_payments >= missed_threshold
        long_unemployed = (not h.employed) and h.unemployment_duration > 6
        # Phase 3.5 行为化触发: 连续 K 月负资产 → 强制违约
        # (即使存款仍充足, 理性违约策略: 抛弃钥匙, 走人)
        behavioral_default = h.months_underwater >= underwater_months_threshold

        triggered = (underwater and (payment_stress or long_unemployed)) or behavioral_default
        if not triggered:
            continue

        mortgage = h.mortgage_balance
        recovery_value = house_value * liquidation_discount  # R ≤ M (默认折扣≤1)
        loss = mortgage - recovery_value                     # 银行承担的损失

        # PR-3f: 多银行时按 HH 的 home_bank 走账户调整
        if multi_bank:
            m_bank = bank_by_id[h.home_bank_id]
        else:
            m_bank = bank

        # ── 银行账本: 资产端重组, 资本减损失 ──
        m_bank.loans_to_households = max(  # type: ignore[attr-defined]
            0.0, m_bank.loans_to_households - mortgage  # type: ignore[attr-defined]
        )
        m_bank.reo_value += recovery_value  # type: ignore[attr-defined]
        m_bank.capital -= loss  # type: ignore[attr-defined]
        m_bank.npl_mortgages += mortgage  # type: ignore[attr-defined]
        m_bank.mark_npl(mortgage)  # type: ignore[attr-defined]
        m_bank.npl_writes_off_cumulative += loss  # type: ignore[attr-defined]
        npl_marked += mortgage

        # ── 家庭账本: 房贷归零, 房子所有权转银行 (数量守恒) ──
        units = h.housing_units
        h.mortgage_balance = 0.0
        h.housing_units = 0
        h.months_underwater = 0
        m_bank.reo_properties += units  # type: ignore[attr-defined]

        logger.info(
            f"  Mortgage default: HH {h.id}, LTV={ltv:.2f}, "
            f"months_underwater={h.months_underwater}, "
            f"mortgage={mortgage:.2f}, recovery={recovery_value:.2f}, "
            f"loss={loss:.2f}"
        )

    if npl_marked > 0:
        # fire_sale_pressure 是状态字段, 单值; 不按银行拆分
        state.fire_sale_pressure = min(
            1.0, state.fire_sale_pressure + sum(
                b.reo_properties for b in state.banks
            ) * 0.001
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
