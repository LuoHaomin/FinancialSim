"""Configuration loader for FinancialSim.

Phase 0: minimal config support. Will be expanded in Phase 1.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

# ════════════════════════════════════════════════════════════
# Phase 3 Week A: 部门参数表 (stylized values; 真实数据 Phase 5 校准)
# 未列出的部门名回退到 productivity=1 / price=1 / 均分份额.
# ════════════════════════════════════════════════════════════
# labor_share: 劳动力配置比例 (全部门归一化到 1)
# demand_share: 消费/政府支出的需求流向比例 (资本品部门排除在外, 由投资驱动;
#               在非资本品部门间归一化).
# ⚠️ Week B 校准: demand_share 必须与劳动份额大体成比例 — 若某部门
# demand/labor 比长期 <1, 工资成本吃掉全部收入 → 结构性亏损 → 破产级联
# (实测: energy 5%/10% 时两个月内员工全灭). 非.自洽的份额只该用于压力测试.
# productivity: 全要素生产率 A; price: 初始价格
SECTOR_DEFAULTS: dict[str, dict[str, float]] = {
    "consumer_goods": {"labor_share": 0.40, "demand_share": 0.40,
                       "productivity": 1.0, "price": 1.0},
    "capital":        {"labor_share": 0.10, "demand_share": 0.00,
                       "productivity": 1.0, "price": 1.0},
    "energy":         {"labor_share": 0.10, "demand_share": 0.11,
                       "productivity": 1.0, "price": 1.0},
    "housing_services": {"labor_share": 0.15, "demand_share": 0.17,
                         "productivity": 1.0, "price": 1.0},
    "high_tech":      {"labor_share": 0.10, "demand_share": 0.09,
                       "productivity": 1.2, "price": 1.0},
    "services":       {"labor_share": 0.15, "demand_share": 0.17,
                       "productivity": 1.0, "price": 1.0},
}
CAPITAL_GOODS_SECTORS = ("capital",)


def sector_param(sector: str, key: str, default: float) -> float:
    """读部门参数; 未知部门回退 default."""
    return float(SECTOR_DEFAULTS.get(sector, {}).get(key, default))


class SimConfig(BaseModel):
    """Top-level simulation configuration."""

    name: str = "baseline"
    description: str = ""
    seed: int = 42

    # Time
    n_ticks: int = Field(default=1200, ge=1)
    days_per_month: int = Field(default=30, ge=1)

    # Population
    n_households: int = Field(default=1000, ge=1)
    n_firms_per_sector: int = Field(default=50, ge=1)
    sectors: list[str] = Field(default_factory=lambda: ["consumer_goods"])
    # n_banks 定义在 "Multi-bank (Phase 2)" 分组, 见下文 (此处不重复声明)

    # Initial conditions
    initial_gdp: float = 1000.0
    initial_inflation: float = 0.02
    nairu: float = 0.05
    target_inflation: float = 0.02

    # ── Monetary policy (Taylor Rule) ──
    cb_policy_rate_initial: float = 0.025
    cb_neutral_rate: float = 0.02
    taylor_inflation_coeff: float = 1.5   # π_π
    taylor_output_coeff: float = 0.5      # π_y
    taylor_smoothing: float = 0.85        # 利率平滑 (惯性 Taylor)
    taylor_rate_floor: float = -0.005     # 零利率下限

    # ── Fiscal (Phase 1: 完整预算) ──
    gov_spending_monthly: float = 0.0        # 固定政府购买; 0 = 自动按占潜在产出比例
    gov_spending_share_gdp: float = 0.45     # 自动模式: G = share × 潜在产出
                                             # 稳态校准: (1 − avg_mpc×(1−τ)) ≈ 0.475
    gov_unemployment_benefit: float = 0.5    # 失业救济 per unemployed HH / 月
    income_tax_rate: float = Field(default=0.25, ge=0.0, lt=1.0)
    corp_tax_rate: float = Field(default=0.21, ge=0.0, lt=1.0)
    fiscal_enabled: bool = True

    # ── Banking (利率传导 + 资本监管) ──
    deposit_rate_margin: float = -0.02    # 存款利率 = policy_rate + margin
    loan_rate_base_spread: float = 0.03   # 贷款基础利差
    loan_rate_car_pressure: float = 0.5   # CAR 每低于缓冲 1pt → 利差 +
    car_requirement: float = 0.08         # 资本充足率要求
    car_buffer: float = 0.02              # 缓冲 (低于 requirement+buffer 加价)
    initial_bank_car: float = 0.12         # 初始 CAR 目标 (反解准备金/资本的锚)
    bank_dividend_payout: float = 0.6      # 超额资本的月度分红比例 (给家庭股东)
    bank_dividend_car_target: float = 0.14  # 分红后要保留的 CAR (超额部分才分)

    # ── Bond market (P0-b) ──
    enable_bond_market: bool = False       # ⚠️ 默认关闭 — 见 docs/IMPLEMENTATION.md §5.0 P0-b
    bond_coupon_rate: float = 0.025        # 票息率 (= 默认 policy_rate; 上层可改)
    bond_issuance_household_share: float = 0.7  # 新发债中给家庭的比例 (银行 1-此)
    bond_max_debt_to_gdp: float = 1.5      # 债务/GDP 上限 (debt brake)

    # ── Consumer credit (P0-a) ──
    enable_consumer_credit: bool = False  # ⚠️ 默认关闭 — 同 P0-b 原因
    consumer_loan_spread: float = 0.05    # 消费贷利率相对 policy_rate 的溢价
    consumer_loan_dti_limit: float = 0.40 # DTI 上限
    consumer_loan_term_months: int = 60   # 期限 (5 年)
    consumer_loan_lending_fraction: float = 0.7  # 银行配给: 合格申请中批准的比例

    # ── Firm (投资/折旧/定价) ──
    depreciation_rate: float = 0.01           # δ, 月度
    investment_sensitivity: float = 0.5       # 产出缺口→投资的敏感系数
    calvo_price_prob: float = 0.0             # 卡尔沃调价概率 (0=用库存规则;
                                              # 场景开启时注意加成棘轮会推高通胀)
    calvo_markup_target: float = 0.10         # 目标成本加成
    production_function: str = "linear"       # "linear" | "ces" (Week A)
    sigma_elasticity: float = 0.5             # CES 替代弹性 σ
    alpha_capital: float = 0.3                # CES 资本份额 α
    productivity_growth_monthly: float = 0.0015   # 月度 TFP 增长 (~1.8%/年)
    labor_wage_productivity_indexation: bool = True  # 工资方程是否指数化生产率趋势
    firm_loan_repayment_speed: float = 0.30  # 营运资本贷款月度还本比例 (超工资单盈余部分)

    def normalized_labor_shares(self) -> dict[str, float]:
        """各部门劳动力配置比例 (SECTOR_DEFAULTS 劳动份额归一化)."""
        shares = {s: sector_param(s, "labor_share", 1.0) for s in self.sectors}
        total = sum(shares.values())
        if total <= 0:
            n = max(1, len(shares))
            return dict.fromkeys(shares, 1.0 / n)
        return {s: v / total for s, v in shares.items()}

    def normalized_demand_shares(self) -> dict[str, float]:
        """消费/政府购买在非资本品部门间的需求份额 (归一化).

        资本品部门的产出由企业投资采购驱动, 不直接承接家庭消费.
        """
        non_capital = [
            s for s in self.sectors
            if s not in CAPITAL_GOODS_SECTORS
        ]
        if not non_capital:
            # 退化: 只有资本品部门时所有需求落它身上
            return dict.fromkeys(self.sectors, 1.0)
        raw = {s: sector_param(s, "demand_share", 1.0) for s in non_capital}
        total = sum(raw.values())
        if total <= 0:
            n = len(non_capital)
            return dict.fromkeys(non_capital, 1.0 / n)
        return {s: v / total for s, v in raw.items()}

    # ── Household (消费行为) ──
    wealth_effect_coef: float = 0.0          # λ: 超额财富拉动消费
    unemployment_replacement_rate: float = 0.4  # 救济替代率上限参考

    # ── Heterogeneity (初始化分布) ──
    hh_savings_rate_mean: float = 0.3
    hh_savings_rate_std: float = 0.1
    hh_mpc_mean: float = 0.7
    hh_mpc_std: float = 0.1
    hh_wage_lognormal_sigma: float = 0.3
    hh_initial_deposit_median: float = 20.0

    # ── Labor market (Phase 1+: frictional hiring) ──
    labor_full_employment: bool = False  # False=摩擦失业(默认), True=雇所有人(legacy)
    labor_separation_rate: float = 0.01   # 月度外生离职率 (默认 1%/月 ≈ 12%/年)
    labor_matching_efficiency: float = 0.5  # 匹配效率: f = 1 - exp(-η·V/U)
    labor_wage_adjust_freq: int = 6       # 工资调整频率(月)
    labor_wage_phillips_coeff: float = 0.04  # κ: 失业缺口→工资(年率). 校准2026-08: 0.10 时低失业环境让实际工资持续爬升越过生产率 (200月+50%), 企业毛利转负 → 债务慢性累积至清算.

    # ── Stock market (Phase 3 Week C): Brock-Hommes 异质信念 ──
    enable_stock_market: bool = False     # 默认关闭 (骨架已验证 SFC 干净)
    n_stock_traders: int = 12             # BH 交易者数量 (聚合家庭部门的代理)
    firm_shares_outstanding: int = 500    # 每家企业发行股数 (IPO)
    stock_par_price: float = 10.0         # IPO 票面价锚 (账面权益≤0 时使用)
    stock_liquidity_lambda: float = 0.40  # 价格对超额需求敏感度 (每子步)
    stock_depth: float = 10.0             # 市场深度 (订单归一化分母)
    stock_cost_of_trading: float = 0.001  # 交易成本阈值 (预测边际才下单)
    stock_order_fraction: float = 0.15    # 每子步订单规模上限比例
    bh_temperature: float = 1.0           # fitness softmax 温度
    bh_fitness_decay: float = 0.05        # 旧适应度月衰减率
    stock_substeps_per_month: int = 12    # 月内子步数 (日级近似; Q9 性能阀;
                                          # 校准实测 12 子步时波动聚集 |r_t| autocorr 均值 0.31)
    # ── Week C M2: 家庭组合选择 (deposits ↔ stocks) ──
    hh_risk_tolerance_mean: float = 0.5   # 风险偏好均值 (截断 [0,1])
    hh_risk_tolerance_std: float = 0.2
    portfolio_weight_base: float = 0.05   # 目标股票权重基数
    portfolio_weight_tol_coeff: float = 0.40  # 目标权重 = base + coeff×risk_tolerance
    portfolio_rebalance_speed: float = 0.20   # 每月向目标权重迁移比例

    # ── Week C M3: 交叉持股骨架 ──
    enable_cross_holdings: bool = False      # 默认关闭 (骨架; 经济效应 Week D 接入)
    cross_hold_beta: float = 0.2             # 发行人划给企业股东的股数比例
    cross_hold_m_links: int = 2              # 每发行人持有的持有人连接数 (BA)

    # ── Week D: 投行 + 资管 (需 enable_stock_market=True) ──
    enable_investment_bank: bool = False    # 默认关闭
    enable_asset_manager: bool = False      # 默认关闭
    ib_initial_capital_per_hh: float = 1.0  # 每户认购的投行资本 (元)
    ib_leverage_max: float = 5.0            # 名义杠杆上限
    ib_margin_requirement: float = 0.08     # capital/assets 强平线
    ib_var_budget: float = 2.0              # VaR 预算系数 (lev ≤ k/σ)
    ib_repo_spread: float = 0.01            # 回购利率 = policy + spread
    am_share_of_hh_units: float = 0.30      # 初始代客管理的家庭持仓比例
    am_base_redemption_rate: float = 0.02   # 基础月赎回率
    am_redemption_sensitivity: float = 1.5  # 赎回率对负收益敏感度
    am_subscription_momentum: float = 0.01  # 正动量时的申购率

    # ── Week E-M1: 供应链 IO (中间品 = 能源投入) ──
    enable_supply_chain: bool = False        # 默认关闭
    io_input_share_default: float = 0.08     # 各部门产量价值中能源投入占比
    io_input_shares: dict[str, float] = Field(default_factory=lambda: {
        "consumer_goods": 0.10,
        "capital": 0.08,
        "energy": 0.00,
        "housing_services": 0.05,
        "high_tech": 0.06,
        "services": 0.04,
    })
    io_capacity_warning_ratio: float = 0.95  # 利用率低于此值告警 (教学诊断)

    # ── Firm dividends (Week B): 企业超额现金按比例分给家庭股东 ──
    enable_firm_dividends: bool = True
    firm_dividend_payout: float = 0.40        # 每月对"工资单倍数以上"现金的分红比例

    # ── Labor market (Phase 3 Week B: 动态劳动需求 + 疤痕效应) ──
    labor_adjust_up_speed: float = 0.15     # 每月最多扩员比例 (销售驱动招聘上限)
    labor_adjust_down_speed: float = 0.06   # 每月最多裁员比例 (向下粘性: 快裁员放大需求塌缩螺旋)
    labor_inventory_buffer: float = 0.20    # 目标产量 = 销量 × (1+库存缓冲)
    labor_demand_response_delay: int = 1    # 雇佣决策对销售的滞后 (月, ≥0; 0=当月)
    wage_scar_discount_rate: float = 0.01   # 长期失业疤痕: 每超宽限月折扣
    wage_scar_grace_months: int = 6         # 宽限期: 失业 ≤ N 月不受折扣
    wage_scar_discount_cap: float = 0.30    # 折扣封顶

    # ── Default & Bankruptcy (Phase 1+ 简化违约) ──
    enable_default: bool = True           # 启用企业违约检测
    firm_default_equity_threshold: float = 0.0  # 净资产 < 阈值 → 违约
    firm_bankruptcy_recovery: float = 0.5  # 资本清算回收率(实物资产折价)
    bank_loss_to_capital: bool = True   # 违约损失直接侵蚀银行资本

    # ── Event system (Phase 1+ ShockEvent) ──
    enable_events: bool = True           # 启用事件注入
    preset_shocks: list[str] = Field(default_factory=list)  # 启用的预设冲击名

    # ── Housing (Phase 2) ──
    enable_housing: bool = True           # 启用住房市场
    housing_rental_yield_target: float = 0.05  # 房价/租金目标比率 (隐含 cap rate)
    housing_price_adjust_speed: float = 0.10   # 月度价格调整速度
    housing_initial_price: float = 120.0      # 初始房价 (自洽: price = rent×12/yield)
    housing_initial_rent: float = 0.5         # 月租金 (0.5×12/0.05 = 120)
    housing_ltv_max: float = 0.80             # 最高 LTV
    housing_initial_ltv: float = 0.70         # 初始抵押组合的平均 LTV
    housing_mortgage_rate_spread: float = 0.02  # 抵押贷款利率溢价
    housing_default_ltv_threshold: float = 1.10  # 房贷余额 > 此 LTV → 违约

    # ── Multi-bank (Phase 2) ──
    n_banks: int = Field(default=1, ge=1)   # 银行数 (默认 1 保持 backward-compat)
    interbank_core_size: int = 3            # Core-Periphery 网络的核心银行数
    interbank_link_density: float = 0.5     # Periphery 连接到核心的概率

    # ── Fire-sale (Phase 2) ──
    fire_sale_price_impact: float = 0.05    # 1 单位抛售压低 X% 的市场价
    bank_failure_car_threshold: float = 0.04  # CAR < 此值触发处置
    lolr_rate_spread: float = 0.01          # 最后贷款人利率溢价
    mortgage_liquidation_discount: float = 0.70  # 止赎房产清算折扣 (0.7 = 70% 价格)
    enable_reo_liquidation: bool = True     # REO 是否卖给家庭 (False=保留在账)

    # Other settings (legacy)
    enable_brock_hommes: bool = False

    @classmethod
    def from_yaml(cls, path: str | Path) -> SimConfig:
        """Load configuration from a YAML file."""
        path = Path(path)
        if not path.exists():
            msg = f"Config file not found: {path}"
            raise FileNotFoundError(msg)
        with path.open("r", encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f)
        return cls(**data)

    @classmethod
    def default(cls) -> SimConfig:
        """Return default configuration."""
        return cls()
