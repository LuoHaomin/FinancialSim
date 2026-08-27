"""Household agent (Phase 0 simplified).

Phase 0 仅包含最简化的字段和行为:
- 状态: id, sector, wage, employed, cash, deposits, income
- 行为: 消费决策 (线性), 储蓄决策 (线性), 就业状态管理

Phase 1 将扩展:
- 永久收入消费 + 财富效应
- 异质性 (教育、储蓄率、MPC)
- 资产配置 (股票/房产/债券)
- 信贷需求
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Household:
    """Phase 0 简化家庭 agent.

    字段:
    - id: 唯一标识
    - sector: 当前就职部门 (None = 失业)
    - wage: 月工资
    - employed: 就业状态
    - unemployment_duration: 失业月数
    - cash: 现金 (在 CB.currency_issued 中)
    - deposits: 银行存款 (在 bank.deposits_from_hh 中)
    - income: 当期可支配收入 (税后)
    - savings_rate: 储蓄倾向 (默认 0.3)
    - mpc: 边际消费倾向 (默认 0.7)
    """

    id: str
    sector: str | None = None

    # ── 就业 ──
    wage: float = 0.0
    employed: bool = True
    unemployment_duration: int = 0

    # ── 金融 ──
    cash: float = 0.0
    deposits: float = 0.0
    income: float = 0.0

    # ── 行为参数 (Phase 1 会改为异质) ──
    savings_rate: float = 0.3
    mpc: float = 0.7

    # ── 决策方法 ──

    def decide_consumption(self) -> float:
        """Phase 0: 线性消费 c = mpc * income."""
        return self.mpc * self.income

    def decide_savings(self) -> float:
        """Phase 0: 线性储蓄 s = savings_rate * income."""
        return self.savings_rate * self.income

    def net_worth(self) -> float:
        """Phase 0: 净资产 = 现金 + 存款 (无负债)."""
        return self.cash + self.deposits

    # ── 就业状态管理 ──

    def lose_job(self) -> None:
        """失业. 重置 unemployment_duration."""
        self.employed = False
        self.unemployment_duration = 0

    def find_job(self, sector: str, wage: float) -> None:
        """找到工作. 重置失业计时, 切换部门."""
        self.employed = True
        self.unemployment_duration = 0
        self.sector = sector
        self.wage = wage

    def tick_unemployment(self) -> None:
        """失业 +1 月. 仅在 unemployed 时调用."""
        if not self.employed:
            self.unemployment_duration += 1
