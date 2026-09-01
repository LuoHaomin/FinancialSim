"""Simulation: 顶层仿真类, 编排 tick + 初始化 + SFC."""
from __future__ import annotations

import numpy as np

from financial_sim.agents.central_bank import CentralBank
from financial_sim.agents.commercial_bank import CommercialBank
from financial_sim.agents.firm import Firm
from financial_sim.agents.government import Government
from financial_sim.agents.household import Household
from financial_sim.config import SimConfig, sector_param
from financial_sim.core.state import SimulationState
from financial_sim.core.step import monthly_tick
from financial_sim.expectations.inflation import InflationExpectation
from financial_sim.markets.bonds import BondMarket
from financial_sim.markets.housing import HousingMarket
from financial_sim.markets.stocks import StockMarket
from financial_sim.network.interbank import InterbankNetwork
from financial_sim.simulation.events import EventManager, build_event_manager
from financial_sim.simulation.rng import RNGManager
from financial_sim.utils.distributions import truncated_normal
from financial_sim.utils.logging import get_logger

logger = get_logger(__name__)


class Simulation:
    """Phase 1 仿真入口.

    使用:
        config = SimConfig.default()
        sim = Simulation(config, seed=42)
        sim.run(n_ticks=12)
        state = sim.state  # 查看宏观变量
    """

    def __init__(
        self,
        config: SimConfig | None = None,
        seed: int | None = None,
        scenario_events: EventManager | None = None,
    ) -> None:
        self.config = config or SimConfig.default()
        self.seed = seed if seed is not None else self.config.seed
        self.rng = RNGManager(seed=self.seed)
        self.state = self._build_state(self.config)
        # P0-c: scenario_events 覆盖自动从 config.preset_shocks 装配的 manager
        if scenario_events is not None:
            self.state.event_manager = scenario_events
        logger.info(
            f"Simulation initialized (seed={self.seed}): "
            f"{len(self.state.households)} HHs, "
            f"1 firm, 1 bank, "
            f"policy_rate={self.state.central_bank.policy_rate:.3f}"
        )

    # ════════════════════════════════════════════════════════════
    # 初始化 (SFC-balanced)
    # ════════════════════════════════════════════════════════════
    def _build_state(self, config: SimConfig) -> SimulationState:
        """构造初始 SFC-balanced state, 家庭参数走命名随机流.

        初始化策略 (VALIDATION.md §13.2 "反向推算"):
        先定各部门的**行为性**存量 (家庭存款/房贷、企业贷款/存款), 再把银行
        准备金与资本作为**平衡项**反解出来, 使初始 CAR 命中目标值:

            A_bank = 存款总额 / (1 − car_target)
            准备金 = A_bank − 贷款总额
            资本   = A_bank − 存款总额 = car_target × A_bank

        央行/政府侧再镜像准备金 (CB 持等额国债). 这样初始 CAR 是**校准出来的**,
        而不是记账凑数的副产品 — 历史 bug: 初始房贷曾用 `bank.capital +=
        total_mortgages` 凑平, 导致 CAR ≈ 1.2, 资本监管通道从第一个 tick 就失效.
        """
        n_hh = config.n_households
        h_rng = self.rng.stream("household_init")

        # ── 央行 (先只设政策参数, 资产负债表在最后镜像) ──
        cb = CentralBank(
            policy_rate=config.cb_policy_rate_initial,
            neutral_rate=config.cb_neutral_rate,
            target_inflation=config.target_inflation,
            taylor_inflation_coeff=config.taylor_inflation_coeff,
            taylor_output_coeff=config.taylor_output_coeff,
        )

        # ── 企业 (贷款融资的营运资金; Phase 3.5 PR-1: 多部门多家企业) ──
        # 每个 sector 创建 n_firms_per_sector 家同质企业 (Phase 3.5: 同部门内
        # 同质; within-sector 异质性留 Phase 4+).
        # 营运资金与初始就业按部门劳动份额 × 每家等分, 残差记在每部门最后一家
        # (保证 Σfirm.debt 严格 == 旧单企业口径; 银行侧镜像逐位相等).
        wage = 1.0
        initial_firm_deposits = float(n_hh) * wage * 2  # 首月工资 + 缓冲
        labor_shares = config.normalized_labor_shares()
        sectors = list(getattr(config, "sectors", ["consumer_goods"])) or [
            "consumer_goods"
        ]
        n_per_sector = max(1, int(getattr(config, "n_firms_per_sector", 50)))
        firms: list[Firm] = []
        allocated_dep = 0.0
        allocated_emp = 0
        for si, sector in enumerate(sectors):
            sector_share = labor_shares.get(sector, 1.0 / len(sectors))
            sector_dep = initial_firm_deposits * sector_share
            sector_emp_total = int(round(n_hh * sector_share))
            last_sector = si == len(sectors) - 1
            for fi in range(n_per_sector):
                last_in_sector = fi == n_per_sector - 1
                # dep 分配: 每部门最后一家吸收残差 (SFC 逐位相等)
                if last_sector and last_in_sector:
                    dep = initial_firm_deposits - allocated_dep
                    emp = n_hh - allocated_emp
                elif last_in_sector:
                    # 同部门最后一家: 吸收部门内残差
                    expected_dep = sector_dep
                    actual_dep_so_far = sum(
                        f.deposits for f in firms
                        if f.sector == sector
                    )
                    dep = expected_dep - actual_dep_so_far
                    expected_emp = sector_emp_total
                    actual_emp_so_far = sum(
                        f.employees for f in firms
                        if f.sector == sector
                    )
                    emp = expected_emp - actual_emp_so_far
                else:
                    dep = round(sector_dep / n_per_sector, 10)
                    emp = int(round(sector_emp_total / n_per_sector))
                firms.append(Firm(
                    id=f"firm_{si}_{fi}_{sector}",
                    sector=sector,
                    productivity=sector_param(sector, "productivity", 1.0),
                    price=sector_param(sector, "price", 1.0),
                    wage_offered=wage,
                    employees=max(0, emp),
                    baseline_employees=max(0, emp),
                    deposits=dep,
                    debt=dep,
                    depreciation_rate=config.depreciation_rate,
                    investment_sensitivity=config.investment_sensitivity,
                    calvo_price_prob=config.calvo_price_prob,
                    calvo_markup_target=config.calvo_markup_target,
                    production_function=getattr(
                        config, "production_function", "linear"
                    ),
                    sigma_elasticity=float(getattr(config, "sigma_elasticity", 0.5)),
                    alpha_capital=float(getattr(config, "alpha_capital", 0.3)),
                    default_equity_threshold=getattr(
                        config, "firm_default_equity_threshold", 0.0
                    ),
                ))
                allocated_dep += dep
                allocated_emp += max(0, emp)
        firm = firms[0]

        # ── 家庭 (异质: 储蓄率/MPC 截断正态; 工资对数正态) ──
        savings_draws = truncated_normal(
            h_rng, config.hh_savings_rate_mean, config.hh_savings_rate_std, 0.0, 0.95, n_hh,
        )
        mpc_draws = truncated_normal(
            h_rng, config.hh_mpc_mean, config.hh_mpc_std, 0.05, 1.0, n_hh,
        )
        wage_draws = h_rng.lognormal(
            mean=float(np.log(wage)), sigma=config.hh_wage_lognormal_sigma, size=n_hh
        )
        deposits_draws = h_rng.lognormal(
            mean=float(np.log(config.hh_initial_deposit_median)), sigma=0.6, size=n_hh
        )
        households = [
            Household(
                id=f"h_{i:04d}",
                sector="consumer_goods",
                wage=float(wage_draws[i]),
                deposits=float(deposits_draws[i]),
                savings_rate=float(savings_draws[i]),
                mpc=float(mpc_draws[i]),
                wealth_effect_coef=config.wealth_effect_coef,
            )
            for i in range(n_hh)
        ]
        for h in households:
            h.permanent_income = h.wage

        # 初始就业归属: 按企业顺序切分家庭, 写 employer_id (工资支付/失业归属用)
        hh_cursor = 0
        for f in firms:
            for h in households[hh_cursor : hh_cursor + f.employees]:
                h.sector = f.sector
                h.employer_id = f.id
            hh_cursor += f.employees

        # ── Phase 2: 住房市场 + 初始房贷 (纯信用创造) ──
        housing = HousingMarket.from_config(config) if bool(
            getattr(config, "enable_housing", True)
        ) else None
        total_mortgages = 0.0
        if housing is not None:
            # 实物存量: 一户一套自住房 (房屋是既存资产, 不通过银行融资)
            housing.total_units = n_hh
            for h in households:
                h.housing_units = 1
                h.mortgage_balance = 0.0
                h.mortgage_rate = (
                    config.cb_policy_rate_initial + housing.mortgage_rate_spread
                )

            # 给存款较多的一半家庭发放初始房贷, 启动 mortgage channel.
            # 记账 (内生信用创造, 两笔同时出现在银行账上, 不需要准备金/资本):
            #   HH: mortgage +M, deposits +M   ↔  Bank: loans_to_hh +M, deposits +M
            # 经济含义: 房贷买房的钱付给了上一任房主 (同属家庭部门), 因此家庭部门
            # 的存款净增 M, 资本/准备金/政府债务均不参与.
            initial_mortgage_ltv = float(getattr(config, "housing_initial_ltv", 0.70))
            sorted_hh = sorted(households, key=lambda h: h.deposits, reverse=True)
            for h in sorted_hh[: n_hh // 2]:
                mortgage = housing.price * initial_mortgage_ltv
                h.mortgage_balance = mortgage
                h.deposits += mortgage
                total_mortgages += mortgage

        # ── 银行: 准备金与资本作为平衡项反解 (命中目标 CAR) ──
        hh_total_deposits = sum(h.deposits for h in households)
        firm_deposits_actual = sum(f.deposits for f in firms)
        total_deposits = hh_total_deposits + firm_deposits_actual
        total_loans = firm_deposits_actual + total_mortgages
        car_target = float(getattr(config, "initial_bank_car", 0.12))
        car_target = min(max(car_target, 0.0), 0.9)
        total_bank_assets = total_deposits / (1.0 - car_target)
        total_reserves = total_bank_assets - total_loans
        if total_reserves < 0:
            # 贷款已超过目标资产规模 → 退化为"零准备金, 资本吸收残差"
            total_reserves = 0.0
            total_bank_assets = total_loans

        n_banks = max(1, int(getattr(config, "n_banks", 1)))
        banks: list[CommercialBank] = []

        # 部门聚合 (工资/消费/政府/税收) 资金流只能记在一家银行上, 因为
        # core/step.py 的 _bank_cycle() 等函数只用 state.bank (= banks[0]).
        # 这是一个**主银行语义**简化: 多银行时其余银行只参与同业网络与逐银行
        # 政策, 不直接吸收部门资金流.
        # 准备金分配: 主银行持有全部 (因为部门聚合准备金也只在主银行账上);
        # 外围银行 reserves = 0, 仅靠 interbank_claims 持有同业债权.
        for b_idx in range(n_banks):
            bank = CommercialBank(
                id=f"bank_{b_idx + 1}",
                tier=1 if b_idx < int(getattr(config, "interbank_core_size", 3)) else 2,
                reserves=total_reserves if b_idx == 0 else 0.0,
                car_requirement=config.car_requirement,
                car_buffer=config.car_buffer,
                loan_rate_base_spread=config.loan_rate_base_spread,
                loan_rate_car_pressure=config.loan_rate_car_pressure,
                deposit_rate_margin=config.deposit_rate_margin,
                mortgage_rate_spread=getattr(config, "housing_mortgage_rate_spread", 0.02),
            )
            banks.append(bank)

        # 主银行持有部门聚合的存贷款 (企业侧 = 各企业求和, 镜像逐位一致)
        # 单银行模式: 主银行聚合所有 deposit/loan; 多银行模式: PR-2 init 段拆分.
        bank = banks[0]
        if n_banks == 1:
            bank.loans_to_firms = firm_deposits_actual
            bank.loans_to_households = total_mortgages
            bank.deposits_from_firms = firm_deposits_actual
            bank.deposits_from_hh = hh_total_deposits
            # 资本 = A − L (主银行单独平衡, 余下银行只放同业敞口)
            bank.capital = bank.total_assets() - bank.total_liabilities()

        # ── Phase 3.5 PR-2: 多银行真拆分 init ──
        # n_banks=1 维持主银行语义 (旧路径, 优化)
        # n_banks>=2: 每家 HH/firm 随机选 home_bank; market_share 由
        #   该银行的实际存款份额决定 (HH deposits 比例); 用于 PR-3 step 拆分.
        b_rng = self.rng.stream("bank_assignment")
        if n_banks == 1:
            # 全部走 banks[0]
            for h in households:
                h.home_bank_id = banks[0].id
            for f in firms:
                f.home_bank_id = banks[0].id
            banks[0].market_share = 1.0
        else:
            # PR-2 init: 分配 home_bank_id + market_share + 同步拆 reserves/deposits/loans
            # (PR-3d/e 不必再回头改 init)
            bank_ids = [b.id for b in banks]
            hh_assignments = b_rng.integers(0, n_banks, size=n_hh)
            for i, h in enumerate(households):
                h.home_bank_id = bank_ids[int(hh_assignments[i])]
            for f in firms:
                f.home_bank_id = bank_ids[int(b_rng.integers(0, n_banks))]
            # market_share = HH deposit-weighted (反映真实存款分配)
            for b in banks:
                total_dep_for_bank = sum(
                    h.deposits for h in households
                    if h.home_bank_id == b.id
                )
                b.market_share = total_dep_for_bank / max(1e-9, hh_total_deposits)
            banks[0].market_share += 1.0 - sum(b.market_share for b in banks)

            # 拆分 deposits + reserves per home_bank
            # ⚠️ loan (firm loan + mortgage) 暂留 banks[0], PR-3d/e 改造
            # _bank_cycle / _housing_cycle 时同步拆分. 否则 init 后
            # firm debt 减少但 bank loan 未减 → 镜像不平衡.
            for b in banks:
                b.deposits_from_hh = sum(
                    h.deposits for h in households
                    if h.home_bank_id == b.id
                )
                b.deposits_from_firms = sum(
                    f.deposits for f in firms
                    if f.home_bank_id == b.id
                )
            # firm loan 按 home_bank 分配 (PR-3d 镜像; 之前暂留 banks[0] 会导致
            # firm 在 bank_3 还款时 banks[0].loans_to_firms 不变 → 镜像不平衡)
            for b in banks:
                    b.loans_to_firms = sum(
                        f.debt for f in firms if f.home_bank_id == b.id
                    )
            # 房贷按 home_bank 分配 (PR-3e: HH 月供走 home_bank → 必须镜像分配)
            for b in banks:
                    b.loans_to_households = sum(
                        h.mortgage_balance for h in households
                        if h.home_bank_id == b.id
                    )
            # 残差给 banks[0] (浮点尾差)
            banks[0].loans_to_households += total_mortgages - sum(
                b.loans_to_households for b in banks
            )
            # reserves 按 market_share 分配 (残差 banks[0] 吸收)
            for b in banks:
                b.reserves = total_reserves * b.market_share
            banks[0].reserves += total_reserves - sum(
                b.reserves for b in banks
            )
            # 每家银行资本 = A_i − L_i (自身 BS 自然平衡)
            for b in banks:
                b.capital = b.total_assets() - b.total_liabilities()
            logger.info(
                f"PR-2 multi-bank init: n_banks={n_banks}, "
                f"market_shares={[round(b.market_share, 3) for b in banks]}, "
                f"bank_caps={[round(b.capital, 2) for b in banks]}"
            )

        # ── 同业网络 (Phase 2): claims/debt 双边同额, 聚合恒等式不变 ──
        # ⚠️ claims/debt 是**银行间**内部资产/负债, 不会改变聚合 BS 恒等式,
        # 因此**不**应调整任何银行的 capital 字段. 这里的主银行资本已在前面
        # 锁定, 外围银行初始 capital=0; 同业敞口的产生是"市场把准备金重新
        # 分配到银行间", 而不是凭空创造/销毁资本.
        # (历史 bug: 早期版本把 `creditor.capital += amount` 写在了这里,
        # 导致聚合 BS 不平衡 −2409 单位, 第一 tick 就被 SFC 检查捕获.)
        # Phase 3.5 PR-4: 多银行时启用同业网络 (InterbankNetwork).
        # - n_banks=1: 维持 None (单银行无同业需求)
        # - n_banks>=2: 构造 Core-Periphery 静态拓扑 + 平均初始敞口
        #   (PR-4-rewire 后续季度重连)
        interbank: InterbankNetwork | None = None
        if n_banks >= 2:
            ib_rng = self.rng.stream("interbank_init")
            avg_ib_exposure = float(
                getattr(config, "interbank_avg_exposure", 50.0)
            )
            interbank = InterbankNetwork.build_core_periphery(
                bank_ids=[b.id for b in banks],
                core_size=int(getattr(config, "interbank_core_size", 3)),
                link_density=float(
                    getattr(config, "interbank_link_density", 0.5)
                ),
                avg_exposure=avg_ib_exposure,
                rng=ib_rng,
            )
            # 把初始同业敞口分配到银行的 interbank_claims/debt (SFC 自平衡:
            # 每笔敞口的 lender 是另一笔的 borrower, Σ=0)
            for (creditor_id, debtor_id), amt in interbank.exposures.items():
                cred = next(
                    (b for b in banks if b.id == creditor_id), None
                )
                debe = next(
                    (b for b in banks if b.id == debtor_id), None
                )
                if cred is not None and debe is not None:
                    cred.interbank_claims += amt
                    debe.interbank_debt += amt
            logger.info(
                f"PR-4 interbank init: n_banks={n_banks}, "
                f"avg_exposure={avg_ib_exposure}, "
                f"edges={len(interbank.exposures)}"
            )

        # ── 央行 + 政府: 镜像准备金 (CB 持等额国债) ──
        cb.bank_reserves = total_reserves
        cb.gov_bonds = total_reserves
        government = Government(
            debt=total_reserves,
            gov_spending=config.gov_spending_monthly if config.fiscal_enabled else 0.0,
            transfers=0.0,
            interest_rate=config.cb_policy_rate_initial,
        )

        # ── Phase 1+: 事件系统 (从 config.preset_shocks 自动装配) ──
        em: EventManager | None = None
        if bool(getattr(config, "enable_events", True)) and getattr(
            config, "preset_shocks", None
        ):
            em = build_event_manager(config.preset_shocks)

        # ── Phase 3 前置 P0-b: 债券市场 ──
        bond_market: BondMarket | None = None
        if bool(getattr(config, "enable_bond_market", True)):
            bond_market = BondMarket(
                outstanding=0.0,
                coupon_rate=float(
                    getattr(config, "bond_coupon_rate", 0.025)
                ),
            )

        # ── Phase 3 Week C: 股票市场 + IPO ──
        # 每家企业发行 firm_shares_outstanding 股; 全部由家庭部门按存款比例
        # 认购 (初始为账面置换: 家庭存款→持仓, IPO 价 = 账面权益/股).
        # ⚠️ SFC 简化约定 (文档化): 建模上视股票由家庭"在初始时刻以既存财富
        # 交换取得", 初始不产生银行科目变动 — 与住房"既存资产"同一处理.
        stock_market: StockMarket | None = None
        cross_edges: dict = {}  # 仅在股票市场块内赋值; 股票关+交叉持股开的组合下保持空
        if bool(getattr(config, "enable_stock_market", False)):
            shares_per_firm = int(getattr(config, "firm_shares_outstanding", 500))
            total_supply = shares_per_firm * len(firms)
            for f in firms:
                f.shares_outstanding = shares_per_firm
            hh_dep_init = sum(h.deposits for h in households)
            if total_supply > 0 and hh_dep_init > 0:
                book_equity = sum(
                    max(0.0, f.deposits + f.inventory + f.capital - f.debt)
                    for f in firms
                )
                stock_market = StockMarket.from_config(
                    config, traders_n=int(getattr(config, "n_stock_traders", 12))
                )
                stock_market.supply_units = float(total_supply)
                par = float(getattr(config, "stock_par_price", 10.0))
                ipo_price = (
                    book_equity / total_supply
                    if book_equity > 0 else par      # 账面权益为零时用票面锚
                )
                stock_market.price = max(ipo_price, 0.01)
                stock_market.price_history.append(stock_market.price)
                tol_draws = truncated_normal(
                    h_rng,
                    config.hh_risk_tolerance_mean,
                    config.hh_risk_tolerance_std, 0.01, 1.0, n_hh,
                )
                # ── Week C M3: 交叉持股 — 发行人把 beta 比例股数划给企业股东 ──
                cross_net = None
                if bool(getattr(config, "enable_cross_holdings", False)):
                    from financial_sim.network.cross_holdings import (
                        build_cross_holdings,
                    )
                    ch_rng = self.rng.stream("cross_holdings")
                    cross_net = build_cross_holdings(
                        firms,
                        beta=float(getattr(config, "cross_hold_beta", 0.2)),
                        rng=ch_rng,
                        m_links=int(getattr(config, "cross_hold_m_links", 2)),
                    )
                issued_to_firms = (
                    cross_net.issued_units_to_firms() if cross_net else {}
                )

                hh_supply = total_supply - sum(issued_to_firms.values())
                for i, h in enumerate(households):
                    h.risk_tolerance = float(tol_draws[i])
                    h.stock_units = hh_supply * h.deposits / hh_dep_init
                if cross_net is not None:
                    cross_edges = {
                        hid: dict(tgt) for hid, tgt in cross_net.edges.items()
                    }
                    for f in firms:
                        f.shares_held_by_firms = float(
                            issued_to_firms.get(f.id, 0.0)
                        )

        # ── Phase 3 Week D: 投行 + 资管 (须先开启股票市场) ──
        investment_bank = None
        asset_manager = None
        if stock_market is not None:
            if bool(getattr(config, "enable_investment_bank", False)):
                from financial_sim.agents.investment_bank import InvestmentBank
                ib_cap_total = float(
                    getattr(config, "ib_initial_capital_per_hh", 1.0)
                ) * n_hh
                # 家庭按存款比例认购投行资本:
                #   h.deposits ↓ / bank.deposits_from_hh ↓
                #   ib.deposits ↑ / ib.capital ↑ /
                #   bank.deposits_from_nbfi ↑     (科目转移, 恒等式保持)
                distributed = 0.0
                n_hhs = len(households)
                for i, h in enumerate(households):
                    pay = min(
                        (
                            ib_cap_total * h.deposits / hh_total_deposits
                            if hh_total_deposits > 0 else 0.0
                        ) if i < n_hhs - 1 else ib_cap_total - distributed,
                        h.deposits,
                    )
                    h.deposits -= pay
                    distributed += pay
                investment_bank = InvestmentBank.from_config(config)
                investment_bank.deposits = distributed
                investment_bank.capital = distributed
                bank.deposits_from_hh -= distributed
                bank.deposits_from_nbfi += distributed

            if bool(getattr(config, "enable_asset_manager", False)):
                from financial_sim.agents.asset_manager import AssetManager
                beta_am = float(
                    getattr(config, "am_share_of_hh_units", 0.30)
                )
                asset_manager = AssetManager.from_config(config)
                # 家庭按比例把持仓过户给基金换份额 (NAV 平价, 零现金流):
                #   h.stock_units ↓ / am.stock_units ↑ / 基金份额 ↑
                for h in households:
                    swapped = h.stock_units * beta_am
                    h.stock_units -= swapped
                    h.fund_units += swapped            # 家庭端份额登记 (M2)
                    asset_manager.stock_units += swapped
                    asset_manager.fund_units_outstanding += swapped

        return SimulationState(
            t=0,
            config=config,
            households=households,
            firms=firms,
            bank=bank,
            banks=banks,
            government=government,
            central_bank=cb,
            real_gdp=0.0,
            nominal_gdp=0.0,
            inflation_yoy=config.initial_inflation,
            unemployment_rate=0.0,
            potential_gdp=float(n_hh),
            price_level=firm.price,
            inflation_expectation=InflationExpectation(
                value=config.initial_inflation, anchor=config.target_inflation
            ),
            rng_manager=self.rng,
            event_manager=em,
            housing_market=housing,
            housing_price=housing.price if housing else 200.0,
            interbank_network=interbank,
            bond_market=bond_market,
            stock_market=stock_market,
            cross_holdings=cross_edges if bool(
                getattr(config, "enable_cross_holdings", False)
            ) else {},
            investment_bank=investment_bank,
            asset_manager=asset_manager,
        )

    # ════════════════════════════════════════════════════════════
    # Tick 编排
    # ════════════════════════════════════════════════════════════
    def step(self) -> None:
        """执行一个 tick."""
        monthly_tick(self.state)

    def run(self, n_ticks: int | None = None) -> SimulationState:
        """运行 n_ticks 个 tick. 默认用 config.n_ticks."""
        n = n_ticks or self.config.n_ticks
        logger.info(f"Running {n} ticks from t={self.state.t}")
        for i in range(n):
            self.step()
            if i % 12 == 0:
                logger.info(
                    f"  t={self.state.t}: GDP={self.state.real_gdp:.2f}, "
                    f"infl={self.state.inflation_yoy:.2%}, "
                    f"unemp={self.state.unemployment_rate:.2%}, "
                    f"SFC_violations={sum(len(v) for v in self.state.sfc_violations)}"
                )
        return self.state

    # ════════════════════════════════════════════════════════════
    # 便捷方法
    # ════════════════════════════════════════════════════════════
    def reset(self) -> None:
        """重置到初始状态 (同 seed 完全复现)."""
        self.rng.reset()
        self.state = self._build_state(self.config)


# ════════════════════════════════════════════════════════════
# 多银行聚合视图 (仅用于报告; 校验在 build_balance_sheets 现场求和)
# ════════════════════════════════════════════════════════════
def _aggregate_banks(banks: list[CommercialBank]) -> CommercialBank:
    """把所有银行聚合成一个虚拟银行 (只读视图, 不可用于记账!)."""
    agg = CommercialBank(id="agg_bank", tier=1)
    agg.reserves = sum(b.reserves for b in banks)
    agg.loans_to_firms = sum(b.loans_to_firms for b in banks)
    agg.loans_to_households = sum(b.loans_to_households for b in banks)
    agg.gov_bonds_held = sum(b.gov_bonds_held for b in banks)
    agg.interbank_claims = sum(b.interbank_claims for b in banks)
    agg.deposits_from_hh = sum(b.deposits_from_hh for b in banks)
    agg.deposits_from_firms = sum(b.deposits_from_firms for b in banks)
    agg.interbank_debt = sum(b.interbank_debt for b in banks)
    agg.lolr_debt = sum(b.lolr_debt for b in banks)
    agg.capital = sum(b.capital for b in banks)
    agg.npl_amount = sum(b.npl_amount for b in banks)
    agg.npl_writes_off_cumulative = sum(b.npl_writes_off_cumulative for b in banks)
    agg.npl_mortgages = sum(b.npl_mortgages for b in banks)
    return agg
