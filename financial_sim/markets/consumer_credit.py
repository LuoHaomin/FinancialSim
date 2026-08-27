"""消费信贷市场 — 别名给 markets.credit, 保持命名直观.

历史: 第一版放在 markets/credit.py, 与 commercial_bank 命名风格冲突;
改名为 consumer_credit.py 后, 原文件作为别名继续存在以兼容旧 import 路径.
"""
from financial_sim.markets.credit import ConsumerCreditMarket

__all__ = ["ConsumerCreditMarket"]
