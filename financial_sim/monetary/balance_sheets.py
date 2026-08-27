"""Sector balance sheets (5 classes).

These are the foundation of Stock-Flow Consistency (SFC).
Every transaction must respect: sum_assets() == sum_liabilities() + net_worth.

设计要点:
- 普通部门 (Household/Firm/Government): NW = sum_assets() - sum_liabilities()
- 资本独立部门 (CommercialBank/CentralBank): NW = capital 字段
  - 不变量: sum_assets() == sum_liabilities() + capital
  - 当不变量违反时, SFC 校验失败
"""
from __future__ import annotations

from dataclasses import dataclass


# ════════════════════════════════════════════════════════════
# HouseholdBalanceSheet
# ════════════════════════════════════════════════════════════
@dataclass
class HouseholdBalanceSheet:
    """家庭部门资产负债表.

    资产: 现金、存款、股票、债券、自住房、投资房、耐用品
    负债: 房贷、消费贷、其他债务
    """

    # ── 资产 ──
    cash: float = 0.0
    deposits: float = 0.0
    stocks: float = 0.0
    bonds: float = 0.0
    housing_self: float = 0.0
    housing_investment: float = 0.0
    consumer_durables: float = 0.0
    # ── 负债 ──
    mortgage: float = 0.0
    consumer_loan: float = 0.0
    other_debt: float = 0.0

    def sum_assets(self) -> float:
        return (
            self.cash + self.deposits + self.stocks + self.bonds
            + self.housing_self + self.housing_investment
            + self.consumer_durables
        )

    def sum_liabilities(self) -> float:
        return self.mortgage + self.consumer_loan + self.other_debt

    @property
    def net_worth(self) -> float:
        return self.sum_assets() - self.sum_liabilities()


# ════════════════════════════════════════════════════════════
# FirmBalanceSheet
# ════════════════════════════════════════════════════════════
@dataclass
class FirmBalanceSheet:
    """企业部门资产负债表.

    资产: 现金、存款、存货、资本、应收账款
    负债: 银行贷款、公司债、应付账款
    """

    # ── 资产 ──
    cash: float = 0.0
    deposits: float = 0.0
    inventories: float = 0.0
    capital_stock: float = 0.0
    interfirm_claims: float = 0.0
    stocks: float = 0.0                    # 持有其他企业股权市值 (Week C M3)
    # ── 负债 ──
    bank_loans: float = 0.0
    bonds_issued: float = 0.0
    accounts_payable: float = 0.0
    minority_equity: float = 0.0           # 被其他企业持有的本企业股权 (镜像科目)

    def sum_assets(self) -> float:
        return (
            self.cash + self.deposits + self.inventories
            + self.capital_stock + self.interfirm_claims
            + self.stocks
        )

    def sum_liabilities(self) -> float:
        return (
            self.bank_loans + self.bonds_issued
            + self.accounts_payable + self.minority_equity
        )

    @property
    def net_worth(self) -> float:
        return self.sum_assets() - self.sum_liabilities()


# ════════════════════════════════════════════════════════════
# CommercialBankBalanceSheet
# ════════════════════════════════════════════════════════════
@dataclass
class CommercialBankBalanceSheet:
    """商业银行部门资产负债表（聚合）.

    资本独立追踪: NW = capital 字段.
    不变量: sum_assets() == sum_liabilities() + capital
    """

    # ── 资产 ──
    reserves: float = 0.0
    loans_to_firms: float = 0.0
    loans_to_households: float = 0.0
    gov_bonds_held: float = 0.0
    interbank_claims: float = 0.0
    reo_value: float = 0.0          # 止赎房产 (实物资产, 按清算价入账)
    seized_assets: float = 0.0      # 破产企业清算资产接收值 (Phase 3 Week A)
    repo_claims: float = 0.0        # 回购融出债权 (Week D)
    # ── 负债 ──
    deposits_from_hh: float = 0.0
    deposits_from_firms: float = 0.0
    deposits_from_nbfi: float = 0.0     # 非银金融机构存款 (Week D)
    interbank_debt: float = 0.0
    bonds_issued: float = 0.0
    # ── 资本 ──
    capital: float = 0.0

    def sum_assets(self) -> float:
        return (
            self.reserves + self.loans_to_firms + self.loans_to_households
            + self.gov_bonds_held + self.interbank_claims + self.reo_value
            +self.seized_assets
            + getattr(self, 'repo_claims', 0.0)
        )

    def sum_liabilities(self) -> float:
        return (
            self.deposits_from_hh + self.deposits_from_firms
            + self.deposits_from_nbfi + self.interbank_debt
            + self.bonds_issued
        )

    @property
    def net_worth(self) -> float:
        # 银行的 NW = 资本字段. 隐含不变量: A = L + capital.
        return self.capital


# ════════════════════════════════════════════════════════════
# GovernmentBalanceSheet
# ════════════════════════════════════════════════════════════
@dataclass
class GovernmentBalanceSheet:
    """政府部门资产负债表.

    通常 NW 为负 (债务 > 资产).
    """

    # ── 资产 ──
    treasury_deposits: float = 0.0
    other_assets: float = 0.0
    # ── 负债 ──
    bonds_outstanding: float = 0.0

    def sum_assets(self) -> float:
        return self.treasury_deposits + self.other_assets

    def sum_liabilities(self) -> float:
        return self.bonds_outstanding

    @property
    def net_worth(self) -> float:
        return self.sum_assets() - self.sum_liabilities()


# ════════════════════════════════════════════════════════════
# CentralBankBalanceSheet
# ════════════════════════════════════════════════════════════
@dataclass
class CentralBankBalanceSheet:
    """中央银行资产负债表.

    资本独立追踪: NW = capital 字段.
    不变量: sum_assets() == sum_liabilities() + capital
    """

    # ── 资产 ──
    gov_bonds: float = 0.0
    lolr_claims: float = 0.0
    other_assets: float = 0.0
    # ── 负债 ──
    bank_reserves: float = 0.0
    currency_issued: float = 0.0
    treasury_deposits: float = 0.0   # 财政部在 CB 的存款 (政府侧为资产)
    # ── 资本 ──
    capital: float = 0.0

    def sum_assets(self) -> float:
        return self.gov_bonds + self.lolr_claims + self.other_assets

    def sum_liabilities(self) -> float:
        return self.bank_reserves + self.currency_issued + self.treasury_deposits

    @property
    def net_worth(self) -> float:
        return self.capital


# ════════════════════════════════════════════════════════════
# Phase 3 Week D: NBFI 部门 (A = L + capital 资本追踪型)
# ════════════════════════════════════════════════════════════
@dataclass
class InvestmentBankBalanceSheet:
    """投资银行资产负债表.

    资产: 存款(在商行)、持仓市值
    负债: 回购融资
    资本独立追踪: A = L + capital
    """

    # ── 资产 ──
    deposits: float = 0.0            # 在商业银行的存款
    stocks: float = 0.0              # 指数持仓市值
    # ── 负债 ──
    repo_debt: float = 0.0           # 回购融资余额
    # ── 资本 ──
    capital: float = 0.0

    def sum_assets(self) -> float:
        return self.deposits + self.stocks

    def sum_liabilities(self) -> float:
        return self.repo_debt

    @property
    def net_worth(self) -> float:
        return self.capital


@dataclass
class AssetManagerBalanceSheet:
    """资产管理资产负债表.

    代理家庭持仓: 资产 = 现金池 + 持仓市值; 负债 = 基金份额 NAV.
    无自有资本 (收手续费前简化为过账机构): A == L, capital ≡ 0.
    """

    # ── 资产 ──
    deposits: float = 0.0            # 现金缓冲池
    stocks: float = 0.0              # 代客持仓市值
    # ── 负债 ──
    fund_nav_liability: float = 0.0  # 基金份额对家庭的赎回权 (按 NAV 计)
    # ── 资本 ──
    capital: float = 0.0

    def sum_assets(self) -> float:
        return self.deposits + self.stocks

    def sum_liabilities(self) -> float:
        return self.fund_nav_liability

    @property
    def net_worth(self) -> float:
        return self.capital
