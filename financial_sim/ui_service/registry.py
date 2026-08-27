"""SimulationRegistry: 管理多个在后台线程运行的仿真实例.

设计要点 (docs/FRONTEND_DESIGN.md §2):
- 每个打开的仿真 = 一个后台线程逐 tick 调用 monthly_tick
- speed 语义: ticks/秒, 0 = 暂停
- 注册表读锁保护; 单仿真的 step 由其自身锁串行化 (REST 与线程共用)
- 上限 MAX_SIMS 个实例, 超限拒绝创建 (Q14 简化口径)

⚠️ 只读投影原则: 本模块及上层只允许通过 sim.step() 推进仿真,
禁止直接改写任何 agent 字段.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from financial_sim.core.simulation import Simulation
from financial_sim.utils.logging import get_logger

logger = get_logger(__name__)

MAX_SIMS = 8
IDLE_SIM_TTL_SECONDS = 30 * 60     # 暂停且无访问超过 30 分钟 → 自动关闭


def _new_id() -> str:
    """ULID 风格 id; 无依赖时退回到时间戳+随机."""
    try:
        import ulid  # type: ignore[import-not-found]
        return str(ulid.new())
    except Exception:
        import secrets
        return f"{int(time.time() * 1000):x}{secrets.token_hex(4)}"


@dataclass
class RunningSim:
    """一个运行中的仿真 + 它的播放控制状态."""

    sim_id: str
    name: str
    simulation: Simulation
    lock: threading.RLock = field(default_factory=threading.RLock)
    stop_event: threading.Event = field(default_factory=threading.Event)
    speed: float = 0.0          # ticks/秒; 0 = 暂停
    run_to: int | None = None   # 自动停在此 t
    last_used: float = field(default_factory=time.time)

    @property
    def state(self):
        return self.simulation.state

    def meta(self) -> dict:
        with self.lock:
            return {
                "sim_id": self.sim_id,
                "name": self.name,
                "t": self.state.t,
                "n_ticks_config": self.simulation.config.n_ticks,
                "speed": self.speed,
                "paused": self.speed <= 0,
                "sfc_violations": sum(
                    len(v) for v in self.state.sfc_violations
                ),
            }


class SimulationRegistry:
    """进程内仿真注册表 (MVP: 单机自用, 无持久化)."""

    def __init__(self) -> None:
        self._sims: dict[str, RunningSim] = {}
        self._lock = threading.Lock()

    # ── 创建 / 列表 ──

    def create(
        self,
        config,
        events=None,
        name: str = "",
        autostart_speed: float = 0.0,
    ) -> RunningSim:
        with self._lock:
            if len(self._sims) >= MAX_SIMS:
                raise RuntimeError(
                    f"仿真实例已达上限 {MAX_SIMS}; 请先关闭部分再试"
                )
            sim = Simulation(config)
            if events is not None:
                sim.state.event_manager = events
            rs = RunningSim(
                sim_id=_new_id(),
                name=name or getattr(config, "name", "") or "untitled",
                simulation=sim,
            )
            rs.speed = float(autostart_speed)
            self._sims[rs.sim_id] = rs
        t = threading.Thread(target=self._run_loop, args=(rs,), daemon=True)
        t.start()
        return rs

    def list_sims(self) -> list[dict]:
        with self._lock:
            return [rs.meta() for rs in self._sims.values()]

    def get(self, sim_id: str) -> RunningSim | None:
        return self._sims.get(sim_id)

    def close(self, sim_id: str) -> bool:
        rs = self._sims.pop(sim_id, None)
        if rs is None:
            return False
        rs.stop_event.set()
        return True

    # ── 后台运行循环 ──

    def _run_loop(self, rs: RunningSim) -> None:
        """按 speed 节拍推进; 暂停时空转等待."""
        next_due = time.monotonic()
        while not rs.stop_event.is_set():
            if rs.speed <= 0:
                next_due = time.monotonic()
                # 空闲回收: 暂停且超过 TTL 无访问 → 自动清理 (用户痛点)
                if time.time() - rs.last_used > IDLE_SIM_TTL_SECONDS:
                    logger.info(f"auto-close idle sim {rs.sim_id}")
                    rs.stop_event.set()
                    with self._lock:
                        self._sims.pop(rs.sim_id, None)
                    return
                time.sleep(0.05)
                continue
            with rs.lock:
                if rs.run_to is not None and rs.state.t >= rs.run_to:
                    rs.speed = 0.0
                    rs.run_to = None
                    continue
                rs.simulation.step()
            interval = 1.0 / max(rs.speed, 1e-9)
            next_due += interval
            sleep_for = next_due - time.monotonic()
            if sleep_for > 0:
                time.sleep(sleep_for)
            else:
                next_due = time.monotonic()      # 追不上就重置节拍
