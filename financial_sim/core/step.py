"""monthly_tick: 编排一个月的仿真流程.

Phase 0 简化版 (按 docs/SIMULATION.md 8.2 简化):
- 跳过日级循环
- 跳过违约阶段
- 跳过事件系统
- Government 用平衡预算 (Phase 1 改为赤字 + 债务)
"""
from __future__ import annotations

from financial_sim.core.state import SimulationState
from financial_sim.markets.goods import GoodsMarket
from financial_sim.markets.labor import LaborMarket
from financial_sim.monetary.sfc import validate_sfc
from financial_sim.utils.logging import get_logger

logger = get_logger(__name__)


def monthly_tick(
    state: SimulationState,
    goods_market: GoodsMarket | None = None,
    labor_market: LaborMarket | None = None,
) -> None:
    """执行一个月的仿真.

    阶段 (Phase 0 简化):
    1. CB 决策 (Taylor Rule)
    2. 劳动市场出清 (雇佣 + 工资调整)
    3. 工资支付 (firm → HH)
    4. HH 消费 (HH → firm)
    5. 商品市场出清 (价格调整 + 库存更新)
    6. Government (Phase 0 关闭)
    7. 宏观聚合
    8. SFC 校验
    """
    if goods_market is None:
        goods_market = GoodsMarket()
    if labor_market is None:
        labor_market = LaborMarket()

    logger.debug(f"=== Tick {state.t} start ===")

    _cb_decisions(state)
    labor_market.clear(state)
    _pay_wages(state)
    _household_consumption(state)
    goods_market.clear(state)
    goods_market.update_inventory(state)
    _government_cycle(state)
    _aggregate_macros(state)
    _validate_sfc(state)

    state.t += 1


# ════════════════════════════════════════════════════════════
# Phase 1: CB 决策
# ════════════════════════════════════════════════════════════
def _cb_decisions(state: SimulationState) -> None:
    """Taylor Rule 设定政策利率."""
    cb = state.central_bank
    assert cb is not None
    new_rate = cb.taylor_rule(
        inflation=state.inflation_yoy,
        output_gap=state.output_gap,
        smoothing=0.85,  # 惯性
    )
    cb.policy_rate = new_rate


# ════════════════════════════════════════════════════════════
# Phase 3: 工资支付
# ════════════════════════════════════════════════════════════
def _pay_wages(state: SimulationState) -> None:
    """Firm 给所有员工发工资, 钱从 firm.deposits 转到 hh.deposits.

    SFC 更新:
    - firm.deposits -= total_wages
    - hh.deposits += wage (per HH)
    - bank.deposits_from_firms -= total_wages
    - bank.deposits_from_hh += total_wages
    """
    firm = state.firm
    bank = state.bank
    assert firm is not None
    assert bank is not None

    employed_hh = [h for h in state.households if h.employed]
    if not employed_hh:
        return

    total_wages = firm.employees * firm.wage_offered

    # 检查 firm 是否有足够存款
    if firm.deposits < total_wages:
        # Phase 0 简化: 直接从银行借款补足
        shortfall = total_wages - firm.deposits
        firm.debt += shortfall
        bank.loans_to_firms += shortfall
        bank.deposits_from_firms += shortfall
        firm.deposits += shortfall

    # 转移: firm → HH
    firm.deposits -= total_wages
    bank.deposits_from_firms -= total_wages
    bank.deposits_from_hh += total_wages

    # 各 HH 收到工资
    for h in employed_hh:
        h.income = firm.wage_offered
        h.deposits += firm.wage_offered


# ════════════════════════════════════════════════════════════
# Phase 4: 家庭消费
# ════════════════════════════════════════════════════════════
def _household_consumption(state: SimulationState) -> None:
    """HH 决定消费/储蓄, 向 firm 购买商品.

    SFC 更新:
    - hh.deposits -= consumption (per HH)
    - firm.deposits += total_consumption
    - bank.deposits_from_hh -= total_consumption
    - bank.deposits_from_firms += total_consumption
    """
    firm = state.firm
    bank = state.bank
    assert firm is not None
    assert bank is not None

    total_consumption = 0.0
    for h in state.households:
        c = h.decide_consumption()
        if h.deposits < c:
            # 流动性约束: 不能消费超过存款
            c = h.deposits
        h.deposits -= c
        total_consumption += c

    if total_consumption > 0:
        firm.deposits += total_consumption
        firm.inventory = max(0.0, firm.inventory - total_consumption)
        bank.deposits_from_hh -= total_consumption
        bank.deposits_from_firms += total_consumption


# ════════════════════════════════════════════════════════════
# Phase 5: 政府 (平衡预算)
# ════════════════════════════════════════════════════════════
def _government_cycle(state: SimulationState) -> None:
    """Phase 0 简化: 政府行为完全关闭.

    默认 gov_spending = 0, transfers = 0, income_tax_rate = 0, corp_tax_rate = 0,
    所以此循环实际上 no-op.
    保留函数骨架以备 Phase 1 加入:
    - 平衡预算 (tax = spending)
    - 或赤字融资 (gov 发债, CB 买入, 银行准备金增加)
    """
    gov = state.government
    if gov is None:
        return

    # Phase 0: 全部政府活动关闭
    if (
        gov.gov_spending == 0
        and gov.transfers == 0
        and gov.income_tax_rate == 0
        and gov.corp_tax_rate == 0
    ):
        return

    # Phase 1+ 实现 (这里只是骨架, 不在 Phase 0 触发):
    firm = state.firm
    bank = state.bank
    cb = state.central_bank
    assert firm is not None
    assert bank is not None
    assert cb is not None

    total_income = sum(h.income for h in state.households)
    total_profit = firm.profit()
    tax = gov.collect_taxes(total_income=total_income, total_profit=total_profit)
    if tax > 0:
        for h in state.households:
            h.deposits -= h.income * gov.income_tax_rate
        bank.deposits_from_hh -= tax

    # 支出与转移: Phase 1 实现


# ════════════════════════════════════════════════════════════
# Phase 6: 宏观聚合
# ════════════════════════════════════════════════════════════
def _aggregate_macros(state: SimulationState) -> None:
    """计算并存储宏观变量."""
    state.real_gdp = state.total_output()
    state.nominal_gdp = state.real_gdp * (1 + state.inflation_yoy) if state.firm else 0
    state.unemployment_rate = state.unemployment_rate_calc()
    state.output_gap = (
        (state.real_gdp - state.potential_gdp) / state.potential_gdp
        if state.potential_gdp > 0
        else 0
    )
    state.snapshot_macro()


# ════════════════════════════════════════════════════════════
# Phase 7: SFC 校验
# ════════════════════════════════════════════════════════════
def _validate_sfc(state: SimulationState) -> None:
    """构造 BS 字典并校验 SFC."""
    bs_dict = state.build_balance_sheets()
    errors = validate_sfc(bs_dict)
    if errors:
        logger.warning(f"SFC violations at tick {state.t}: {errors}")
        state.sfc_violations.append(errors)
        # Phase 0: 仅记录, 不抛异常 (避免调试时崩溃)
        # Phase 1+: 可改为 raise SFCViolationError(errors)
