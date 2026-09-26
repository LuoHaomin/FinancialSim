"""ShockEvent: 外生冲击系统 (Phase 1+).

设计 (SIMULATION.md §8.3):
- ShockEvent 数据类: 时间 + 目标 + 通道 + 强度 + 持续期
- PRESET_SHOCKS: 命名预设 (rate_hike, energy_price, fiscal_austerity ...)
- EventManager: 在 monthly_tick 触发并应用, 用 RNGManager 保证可复现
- 通道 (channel) 包括:
  - 'policy_rate': 直接调整 cb.policy_rate
  - 'gov_spending': 临时改变 G 的规模系数
  - 'tax_rate':     临时改变所得税率
  - 'wage_shock':   直接改 firm.wage_offered 倍率
  - 'energy_price': 通过 productivity 通道影响 (Phase 1 简化为 wages×(1+shock))
  - 'asset_price':  (Phase 2) 资产价格冲击

SFC 注记: 大多数冲击都是参数层的扰动, 不直接动账目;
但 policy_rate 改变会触发后续银行利率传导.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from financial_sim.utils.logging import get_logger

logger = get_logger(__name__)


# ════════════════════════════════════════════════════════════
# ShockEvent 数据类
# ════════════════════════════════════════════════════════════
@dataclass
class ShockEvent:
    """一次外生冲击.

    字段:
    - name:     事件名 (便于日志与回放)
    - trigger_t: 触发的仿真 tick (state.t == trigger_t 时应用)
    - channel:  影响通道 (见模块 docstring)
    - magnitude: 强度 (通道含义不同, 见 _apply)
    - duration: 持续月数 (0 = 单期; >0 = 持续 N 期)
    - one_shot: True=只触发一次; False=在 duration 期内每月生效
    """

    name: str
    trigger_t: int
    channel: str
    magnitude: float
    duration: int = 1
    one_shot: bool = True

    def is_active_at(self, t: int) -> bool:
        """判断在 t 期是否应触发 (one_shot 在 trigger_t; 否则在 [trigger_t, trigger_t+duration))."""
        if self.one_shot:
            return t == self.trigger_t
        return self.trigger_t <= t < self.trigger_t + self.duration


# ════════════════════════════════════════════════════════════
# 预设冲击库
# ════════════════════════════════════════════════════════════
PRESET_SHOCKS: dict[str, dict[str, Any]] = {
    # 货币: 激进加息 100bp (1 期)
    "rate_hike_100bp": {
        "channel": "policy_rate", "magnitude": 0.01, "duration": 1, "one_shot": True,
    },
    # 货币: 持续紧缩 50bp × 6 月
    "tightening_50bp_6m": {
        "channel": "policy_rate", "magnitude": 0.005, "duration": 6, "one_shot": False,
    },
    # 货币: 持续宽松 50bp × 6 月
    "easing_50bp_6m": {
        "channel": "policy_rate", "magnitude": -0.005, "duration": 6, "one_shot": False,
    },
    # 财政: 紧缩 G 减少 30% (持续 12 月)
    "fiscal_austerity_30p_12m": {
        "channel": "gov_spending", "magnitude": 0.70, "duration": 12, "one_shot": False,
    },
    # 财政: 刺激 G 增加 20% (持续 12 月)
    "fiscal_stimulus_20p_12m": {
        "channel": "gov_spending", "magnitude": 1.20, "duration": 12, "one_shot": False,
    },
    # 税收: 所得税上调 5pp (持续 24 月)
    "tax_hike_5pp_24m": {
        "channel": "tax_rate", "magnitude": 0.05, "duration": 24, "one_shot": False,
    },
    # 工资: 一次性 +10% (冲击式)
    "wage_shock_plus10p": {
        "channel": "wage_shock", "magnitude": 0.10, "duration": 1, "one_shot": True,
    },
    # 工资: 一次性 -10% (冲击式)
    "wage_shock_minus10p": {
        "channel": "wage_shock", "magnitude": -0.10, "duration": 1, "one_shot": True,
    },
    # 能源/进口价格: 通过企业 productivity 通道 (简化)
    "energy_shock_plus30p": {
        "channel": "energy_price", "magnitude": 0.30, "duration": 12, "one_shot": False,
    },
    # 住房: 抵押贷款风险溢价飙升 (2008 型场景核心冲击; yield +4pp 一步到位,
    # 房价经 revalue() 锚定机制逐步向新基本面回归)
    "housing_risk_premium_spike": {
        "channel": "housing_yield_target", "magnitude": 0.04,
        "duration": 1, "one_shot": True,
    },
}


def make_preset_shock(
    name: str, trigger_t: int, override: dict[str, Any] | None = None,
) -> ShockEvent:
    """从预设库创建 ShockEvent. trigger_t 由调用方指定."""
    if name not in PRESET_SHOCKS:
        msg = f"Unknown preset shock: {name}. Available: {list(PRESET_SHOCKS.keys())}"
        raise ValueError(msg)
    cfg = dict(PRESET_SHOCKS[name])
    if override:
        cfg.update(override)
    return ShockEvent(name=name, trigger_t=trigger_t, **cfg)


# ════════════════════════════════════════════════════════════
# EventManager: 在 monthly_tick 调度
# ════════════════════════════════════════════════════════════
class EventManager:
    """管理一组 ShockEvent; 暴露 apply_to_state(state, t) 接口.

    设计选择: 不在 apply 时修改其他 agent, 而是返回一连串 channel 操作,
    由 core.step 决定具体执行路径. 这样测试时易观察, 也避免 EventManager
    直接和 step.py 的子函数耦合.
    """

    def __init__(self, events: list[ShockEvent] | None = None) -> None:
        """初始化管理器.

        Args:
            events: 初始事件列表; 传 None 等价于空列表. 内部复制为新 list,
                外部对原列表的后续修改不影响本管理器.
        """
        self.events: list[ShockEvent] = list(events or [])

    def add(self, event: ShockEvent) -> None:
        """追加单个事件到末尾.

        Args:
            event: 要加入的 ShockEvent 实例.
        """
        self.events.append(event)

    def extend(self, events: list[ShockEvent]) -> None:
        """批量追加事件.

        Args:
            events: 要追加的事件列表; 与 list.extend 语义一致, 即追加全部元素.
        """
        self.events.extend(events)

    def active_at(self, t: int) -> list[ShockEvent]:
        """返回 t 期应触发的所有事件."""
        return [e for e in self.events if e.is_active_at(t)]

    def apply_to_state(self, state: Any, t: int) -> list[ShockEvent]:
        """应用 t 期的冲击, 返回触发的列表 (供 step 层进一步处理).

        直接应用的通道: policy_rate, gov_spending, tax_rate, wage_shock, energy_price.
        资产价格等需要 Phase 2 资产市场, 暂只记录.
        """
        fired = self.active_at(t)
        effects = self.compute_effects(fired)
        self._apply_effects(effects, state)
        for ev in fired:
            logger.debug(
                f"Shock fired at t={t}: {ev.name} "
                f"(channel={ev.channel}, magnitude={ev.magnitude})"
            )
        return fired

    def compute_effects(self, events: list[ShockEvent]) -> dict[str, float]:
        """聚合多个事件的效应 (同一通道的 mag 累加; 替换类通道取最新)."""
        effects: dict[str, float] = {}
        for ev in events:
            if ev.channel == "policy_rate":
                effects["policy_rate_delta"] = (
                    effects.get("policy_rate_delta", 0.0) + ev.magnitude
                )
            elif ev.channel == "gov_spending":
                # 替换: 同通道最后一个为准 (而非累乘)
                effects["gov_spending_mult"] = ev.magnitude
            elif ev.channel == "tax_rate":
                effects["tax_rate_delta"] = (
                    effects.get("tax_rate_delta", 0.0) + ev.magnitude
                )
            elif ev.channel == "wage_shock":
                effects["wage_shock_mult"] = (
                    effects.get("wage_shock_mult", 0.0) + ev.magnitude
                )
            elif ev.channel == "energy_price":
                # 替换: 一个能源冲击替换 productivity 倍率
                effects["energy_price_mult"] = 1.0 / (1.0 + ev.magnitude)
            elif ev.channel == "housing_yield_target":
                effects["housing_yield_delta"] = (
                    effects.get("housing_yield_delta", 0.0) + ev.magnitude
                )
            else:
                logger.warning(f"Unknown shock channel: {ev.channel} (skipped)")
        return effects

    def _apply_effects(self, effects: dict[str, float], state: Any) -> None:
        """把 effects 落到 state (参数层, 不动账目)."""
        if "policy_rate_delta" in effects:
            cb = getattr(state, "central_bank", None)
            if cb is not None:
                cb.policy_rate += effects["policy_rate_delta"]
        # gov_spending_mult 缺失时回退到 1.0 (无冲击语义)
        state._gov_spending_multiplier = effects.get("gov_spending_mult", 1.0)
        if "tax_rate_delta" in effects:
            state._income_tax_rate_override = (
                effects.get("_income_tax_base", 0.25) + effects["tax_rate_delta"]
            )
        else:
            state._income_tax_rate_override = None
        if "wage_shock_mult" in effects:
            for firm in getattr(state, "firms", []) or []:
                firm.wage_offered *= 1.0 + effects["wage_shock_mult"]
        if "energy_price_mult" in effects:
            for firm in getattr(state, "firms", []) or []:
                # 注意: 这是简化的"一次性"应用; 持续冲击会逐月乘以 mult
                firm.productivity *= effects["energy_price_mult"]
        if "housing_yield_delta" in effects:
            housing = getattr(state, "housing_market", None)
            if housing is not None:
                # 风险溢价重定价是持久性水平移动: 直接上调目标 cap rate.
                # revalue() 用 rental_yield_target 作锚 → 永久压低房价路径.
                housing.rental_yield_target += effects["housing_yield_delta"]

    # ── 状态读取 ──

    def get_gov_spending_multiplier(self, state: Any) -> float:
        """读取当前 state 上由 gov_spending 通道设置的支出乘数.

        Args:
            state: 仿真状态对象.

        Returns:
            state 上 _gov_spending_multiplier 的值, 若未设置(无冲击)则回退到 1.0.
        """
        return getattr(state, "_gov_spending_multiplier", 1.0)

    def get_income_tax_rate(self, state: Any, default: float) -> float:
        """读取当前 state 上由 tax_rate 通道设置的所得税率覆盖值.

        Args:
            state: 仿真状态对象.
            default: 未触发 tax_rate 冲击时使用的所得税率基线.

        Returns:
            覆盖值(若有)或 default. 调用方负责把返回值传入财政税计算路径.
        """
        override = getattr(state, "_income_tax_rate_override", None)
        return default if override is None else override


# ════════════════════════════════════════════════════════════
# 工具: 从 preset 名列表构建 EventManager
# ════════════════════════════════════════════════════════════
def build_event_manager(
    preset_names: list[str],
    trigger_offsets: list[int] | None = None,
) -> EventManager:
    """批量构造. trigger_offsets[i] 是相对仿真 t=0 的偏移; 缺省则触发在 t=12."""
    if trigger_offsets is None:
        trigger_offsets = [12] * len(preset_names)
    if len(trigger_offsets) != len(preset_names):
        msg = (
            f"trigger_offsets length {len(trigger_offsets)} != "
            f"preset_names length {len(preset_names)}"
        )
        raise ValueError(msg)
    events = [
        make_preset_shock(name, trigger_t=t)
        for name, t in zip(preset_names, trigger_offsets, strict=True)
    ]
    return EventManager(events)


__all__ = [
    "ShockEvent",
    "EventManager",
    "PRESET_SHOCKS",
    "make_preset_shock",
    "build_event_manager",
]
