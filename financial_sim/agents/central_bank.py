"""CentralBank agent (Phase 0 simplified).

Phase 0 仅包含:
- Taylor Rule 利率设定 (含平滑)
- 公开市场操作 (OMO)

Phase 1 加入:
- 最后贷款人 (LOLR)
- 存款准备金率
- 逆周期资本缓冲
- 多工具协同
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CentralBank:
    """Phase 0 简化中央银行.

    字段:
    - policy_rate: 当前政策利率 (主要工具)
    - target_inflation: 通胀目标 (默认 2%)
    - neutral_rate: 中性利率 (默认 2%)
    - 资产负债表字段 (与 CentralBankBalanceSheet 对应):
      - gov_bonds: 持有国债 (OMO)
      - bank_reserves: 银行准备金 (负债)
      - currency_issued: 流通现金 (负债)
      - capital: CB 资本
    """

    # ── 政策参数 ──
    policy_rate: float = 0.025
    target_inflation: float = 0.02
    neutral_rate: float = 0.02
    taylor_inflation_coeff: float = 1.5
    taylor_output_coeff: float = 0.5
    id: str = "cb_1"  # bond_market 簿记需要 holder id

    # ── 资产负债表 ──
    gov_bonds: float = 0.0
    bank_reserves: float = 0.0
    currency_issued: float = 0.0
    treasury_deposits: float = 0.0   # 财政部存款 (负债; 政府侧为资产)
    capital: float = 0.0

    # ── 决策方法 ──

    def taylor_rule(
        self,
        inflation: float,
        output_gap: float,
        smoothing: float = 0.85,
        rate_floor: float = -0.005,
    ) -> float:
        """Taylor Rule 利率设定 (含平滑).

        公式:
            r_target = r* + 1.5 × (π - π*) + 0.5 × output_gap
            r_new    = smoothing × r_prev + (1 - smoothing) × r_target
            r_new    = max(r_new, rate_floor)

        Parameters
        ----------
        inflation : float
            当前通胀率 (e.g. 0.02 = 2%)
        output_gap : float
            产出缺口 (e.g. -0.02 = 低于潜力 2%)
        smoothing : float
            惯性参数 (0 = 无平滑, 0.85 = 标准)
        rate_floor : float
            利率下限 (默认 -0.5%)
        """
        inflation_gap = inflation - self.target_inflation
        r_target = (
            self.neutral_rate + self.taylor_inflation_coeff * inflation_gap
            + self.taylor_output_coeff * output_gap
        )
        r_new = smoothing * self.policy_rate + (1 - smoothing) * r_target
        return max(r_new, rate_floor)

    def omo_buy(self, amount: float) -> None:
        """公开市场操作: CB 买入国债 → 注入银行准备金.

        资产端: gov_bonds += amount
        负债端: bank_reserves += amount
        """
        if amount <= 0:
            return
        self.gov_bonds += amount
        self.bank_reserves += amount

    def omo_sell(self, amount: float) -> None:
        """公开市场操作: CB 卖出国债 → 吸收银行准备金.

        资产端: gov_bonds -= amount
        负债端: bank_reserves -= amount
        """
        if amount <= 0:
            return
        self.gov_bonds = max(0.0, self.gov_bonds - amount)
        self.bank_reserves = max(0.0, self.bank_reserves - amount)
