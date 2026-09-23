"""FastAPI 服务层 (Phase 4 W1/W2).

只读投影 + 受控干预通道. 三条铁律见 docs/FRONTEND_DESIGN.md §0:
- 状态一律从 ProjectionLayer 投影, 不暴露 agent 引用
- 干预只经 InterventionGateway 构造 ShockEvent 注入
- 全部决策参数可复现 (seed 不变则历史不变)
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from financial_sim.scenarios import list_scenarios, load_scenario
from financial_sim.simulation.events import PRESET_SHOCKS
from financial_sim.ui_service.projection import (
    agent_detail,
    banks_table,
    central_bank_view,
    firms_table,
    government_view,
    households_stats,
    macro_frame,
    network_view,
    sectors_matrix,
    series,
    sfc_view,
    shock_log_view,
    stress_view,
)
from financial_sim.ui_service.registry import RunningSim, SimulationRegistry


class CreateSimRequest(BaseModel):
    scenario: str | None = None          # scenarios/*.yaml 名
    config_yaml: str | None = None       # 或内联 YAML 配置 (二选一)
    autostart_speed: float = 2.0         # ticks/秒; 0 = 创建即暂停
    overrides: dict = Field(default_factory=dict)   # 覆盖 SimConfig 字段


class CommandRequest(BaseModel):
    speed: float | None = None           # 设置速率 (0=暂停)
    step: int = 0                        # 单步推进 N tick


class InterventionBody(BaseModel):
    preset: str | None = None          # PRESET_SHOCKS 名 (推荐)
    channel: str | None = None         # 或自定义通道
    magnitude: float | None = None
    duration: int = 1
    one_shot: bool = True
    trigger_offset: int = 0              # 相对当前 t 的偏移 (≥0)


# 自定义干预通道白名单 (preset 之外唯一可写入口)
CUSTOM_CHANNELS = [
    "policy_rate", "gov_spending", "tax_rate",
    "wage_shock", "energy_price", "housing_yield_target",
]

# 预设冲击的中文说明 (供 /api/meta → 前端渲染)
PRESET_DESCRIPTIONS = {
    "rate_hike_100bp": "激进加息 100bp (单期)",
    "tightening_50bp_6m": "持续紧缩 +50bp × 6 月",
    "easing_50bp_6m": "持续宽松 −50bp × 6 月",
    "fiscal_austerity_30p_12m": "财政紧缩: 支出 −30% × 12 月",
    "fiscal_stimulus_20p_12m": "财政刺激: 支出 +20% × 12 月",
    "tax_hike_5pp_24m": "所得税 +5pp × 24 月",
    "wage_shock_plus10p": "工资一次性 +10%",
    "wage_shock_minus10p": "工资一次性 −10%",
    "energy_shock_plus30p": "能源价格 +30% × 12 月",
    "housing_risk_premium_spike": "房贷风险溢价 +4pp (2008 型)",
}


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例.

    注册全部路由 (仿真生命周期 / 播放控制 / 只读投影 / 干预网关 / WebSocket 流),
    初始化 SimulationRegistry (仿真注册表, 单实例). 工厂函数; 顶层 ``app``
    由模块末尾 ``create_app()`` 调用得到.

    Returns:
        FastAPI: 已装配全部路由的应用实例, 可直接交由 uvicorn 启动.
    """
    app = FastAPI(title="FinancialSim UI Service", version="0.1.0")
    registry = SimulationRegistry()

    # ── 工具 ──

    def _get(sim_id: str) -> RunningSim:
        rs = registry.get(sim_id)
        if rs is None:
            raise HTTPException(404, f"仿真不存在: {sim_id}")
        import time as _t
        rs.last_used = _t.time()      # 触碰活跃时间, 供空闲回收判定
        return rs

    def _validate_shock(channel: str, magnitude: float) -> None:
        known = set(PRESET_SHOCKS.keys()) | set(CUSTOM_CHANNELS)
        if channel not in known:
            raise HTTPException(
                422,
                detail=f"未知冲击通道: {channel}; 可用: {sorted(known)}",
            )
        if not (-10.0 <= magnitude <= 10.0):
            raise HTTPException(422, detail="magnitude 超出 [-10, 10]")

    def _make_event(name: str, trigger_t: int, duration: int = 1,
                    one_shot: bool = True, magnitude: float | None = None,
                    channel_override: str | None = None):
        from financial_sim.simulation.events import ShockEvent

        cfgs = dict(PRESET_SHOCKS.get(name, {}))
        if not cfgs and channel_override:
            cfgs = {"channel": channel_override,
                    "magnitude": magnitude or 0.0}
        cfgs["duration"] = int(duration)
        cfgs["one_shot"] = bool(one_shot)
        if magnitude is not None and channel_override is None:
            cfgs["magnitude"] = float(magnitude)
        return ShockEvent(name=name, trigger_t=int(trigger_t), **cfgs)

    # ── 仿真生命周期 ──

    @app.post("/api/sims")
    def create_sim(req: CreateSimRequest) -> dict:
        """创建新仿真实例.

        两种来源二选一: 内联 YAML ( ``config_yaml`` ) 或 scenarios/ 下的
        预设场景名 ( ``scenario``, 默认 ``"baseline"`` ). ``overrides``
        在加载后再逐字段覆盖 SimConfig.

        Args:
            req: 创建请求体, 含 scenario/config_yaml/autostart_speed/overrides.

        Returns:
            dict: ``{"sim_id": ..., "meta": {...}}`` — sim_id 供后续接口引用.

        Raises:
            HTTPException: 404 场景文件不存在; 422 YAML/参数非法;
                409 注册表已满或同名冲突.
        """
        try:
            if req.config_yaml:
                from financial_sim.config import SimConfig
                config = SimConfig.from_yaml_str(req.config_yaml) \
                    if hasattr(SimConfig, "from_yaml_str") else _yaml_cfg(
                        req.config_yaml
                    )
                for k, v in req.overrides.items():
                    setattr(config, k, v)
                events = None
                name = getattr(config, "name", "inline")
            else:
                scen_name = req.scenario or "baseline"
                config, events = load_scenario(scen_name)
                for k, v in req.overrides.items():
                    setattr(config, k, v)
                name = scen_name
            rs = registry.create(
                config, events=events, name=name,
                autostart_speed=req.autostart_speed,
            )
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        except RuntimeError as e:
            raise HTTPException(409, str(e)) from e
        return {"sim_id": rs.sim_id, "meta": rs.meta()}

    @app.get("/api/sims")
    def list_sims() -> list[dict]:
        """列出注册表中所有活跃仿真实例的元数据.

        Returns:
            list[dict]: 每个元素为 ``rs.meta()`` 输出 (sim_id/name/state/t/speed).
        """
        return registry.list_sims()

    @app.get("/api/sims/{sim_id}")
    def sim_meta(sim_id: str) -> dict:
        """查询单个仿真的当前元数据 (t, speed, 名称, 状态).

        Args:
            sim_id: 仿真 id, 由 ``POST /api/sims`` 返回.

        Returns:
            dict: ``rs.meta()`` 输出.

        Raises:
            HTTPException: 404 仿真不存在.
        """
        return _get(sim_id).meta()

    @app.delete("/api/sims/{sim_id}")
    def close_sim(sim_id: str) -> dict:
        """关闭并清理指定仿真, 释放 SimulationRegistry 中的资源.

        Args:
            sim_id: 待关闭的仿真 id.

        Returns:
            dict: ``{"closed": sim_id}`` — 关闭成功的回执.

        Raises:
            HTTPException: 404 仿真不存在.
        """
        if not registry.close(sim_id):
            raise HTTPException(404, f"仿真不存在: {sim_id}")
        return {"closed": sim_id}

    # ── 播放控制 ──

    @app.post("/api/sims/{sim_id}/command")
    def command(sim_id: str, cmd: CommandRequest) -> dict:
        """播放控制入口: 设置速率或单步推进 N tick.

        ``speed`` 与 ``step`` 可同时给: 先改速率, 再逐 tick 执行 (持锁).

        Args:
            sim_id: 仿真 id.
            cmd: ``{"speed": float|None, "step": int}``; speed 单位 ticks/秒,
                0 表示暂停, 范围 [0, 60].

        Returns:
            dict: ``{"t": 当前 tick, "stepped": 实际推进数, "speed": 当前速率}``.

        Raises:
            HTTPException: 404 仿真不存在; 422 speed 越界.
        """
        rs = _get(sim_id)
        with rs.lock:
            if cmd.speed is not None:
                if cmd.speed < 0 or cmd.speed > 60:
                    raise HTTPException(422, "speed ∈ [0, 60] ticks/秒")
                rs.speed = float(cmd.speed)
            n_steps = max(0, min(int(cmd.step), 1000))
        # step 在锁外逐 tick 执行 (每次持锁), 避免长占锁阻塞读接口
        stepped = 0
        for _ in range(n_steps):
            with rs.lock:
                if rs.stop_event.is_set():
                    break
                rs.simulation.step()
                stepped += 1
        return {"t": rs.state.t, "stepped": stepped, "speed": rs.speed}

    # ── 只读投影 ──

    @app.get("/api/sims/{sim_id}/series")
    def get_series(sim_id: str, from_t: int = 0,
                   to_t: int | None = None) -> dict:
        """拉取一段 tick 区间内的多变量时间序列 (用于前端绘图).

        Args:
            sim_id: 仿真 id.
            from_t: 起始 tick (含), 默认 0.
            to_t: 终止 tick (含); ``None`` 表示到当前 t.

        Returns:
            dict: ``projection.series()`` 输出 (含 series 名 → tick → 值).

        Raises:
            HTTPException: 404 仿真不存在.
        """
        rs = _get(sim_id)
        with rs.lock:
            return series(rs.state, from_t=from_t, to_t=to_t)

    # 注意: 这两条必须在 /agents/{sector} 之前注册, 否则被通配吃掉
    @app.get("/api/sims/{sim_id}/agents/government")
    def gov_view(sim_id: str) -> dict:
        """政府部门主体的当前视图 (收入/支出/债务/赤字等).

        注意: 路径必须在 ``/agents/{sector}`` 之前注册, 否则被通配符吃掉.

        Args:
            sim_id: 仿真 id.

        Returns:
            dict: ``projection.government_view()`` 输出.

        Raises:
            HTTPException: 404 仿真不存在或政府主体缺失.
        """
        rs = _get(sim_id)
        with rs.lock:
            view = government_view(rs.state)
        if view is None:
            raise HTTPException(404, "政府主体不存在")
        return view

    @app.get("/api/sims/{sim_id}/agents/central_bank")
    def cb_view(sim_id: str) -> dict:
        """央行主体当前视图 (政策利率/资产负债表/外汇储备等).

        注意: 路径必须在 ``/agents/{sector}`` 之前注册, 否则被通配符吃掉.

        Args:
            sim_id: 仿真 id.

        Returns:
            dict: ``projection.central_bank_view()`` 输出.

        Raises:
            HTTPException: 404 仿真不存在或央行主体缺失.
        """
        rs = _get(sim_id)
        with rs.lock:
            view = central_bank_view(rs.state)
        if view is None:
            raise HTTPException(404, "央行主体不存在")
        return view

    @app.get("/api/sims/{sim_id}/agents/{sector}")
    def agents_table(sim_id: str, sector: str) -> list[dict]:
        """列表化渲染某部门下全部主体 (firms / banks).

        Args:
            sim_id: 仿真 id.
            sector: 部门名, 当前支持 ``"firms"`` 与 ``"banks"``.

        Returns:
            list[dict]: 每行一个主体的关键指标 (供前端表格).

        Raises:
            HTTPException: 404 仿真不存在或 sector 未知.
        """
        rs = _get(sim_id)
        with rs.lock:
            if sector == "firms":
                return firms_table(rs.state)
            if sector == "banks":
                return banks_table(rs.state)
        raise HTTPException(404, f"未知主体类型: {sector}")

    @app.get("/api/sims/{sim_id}/agent/{sector}/{agent_id}")
    def agent_view(sim_id: str, sector: str, agent_id: str) -> dict:
        """单个主体详情 (资产负债/利润/NAV/杠杆等全字段).

        Args:
            sim_id: 仿真 id.
            sector: 部门名 (firms/banks/households 等).
            agent_id: 主体 id, 由 ``/agents/{sector}`` 列表返回.

        Returns:
            dict: ``projection.agent_detail()`` 输出.

        Raises:
            HTTPException: 404 仿真不存在或 sector/agent_id 找不到.
        """
        rs = _get(sim_id)
        with rs.lock:
            view = agent_detail(rs.state, sector, agent_id)
        if view is None:
            raise HTTPException(404, f"{sector}/{agent_id} 不存在")
        return view

    @app.get("/api/sims/{sim_id}/households")
    def households_panel(sim_id: str) -> dict:
        """居民部门聚合统计 (收入分位/财富分布/储蓄率等).

        Args:
            sim_id: 仿真 id.

        Returns:
            dict: ``projection.households_stats()`` 输出.

        Raises:
            HTTPException: 404 仿真不存在.
        """
        rs = _get(sim_id)
        with rs.lock:
            return households_stats(rs.state)

    @app.get("/api/sims/{sim_id}/sectors")
    def sectors(sim_id: str) -> dict:
        """部门级交叉矩阵 (各部门的资产/负债/净头寸对位).

        Args:
            sim_id: 仿真 id.

        Returns:
            dict: ``projection.sectors_matrix()`` 输出, 适合 SFC 流向桑基图渲染.

        Raises:
            HTTPException: 404 仿真不存在.
        """
        rs = _get(sim_id)
        with rs.lock:
            return sectors_matrix(rs.state)

    @app.get("/api/sims/{sim_id}/network/{kind}")
    def network(sim_id: str, kind: str) -> dict:
        """网络结构视图 (节点 + 边), 供前端力导向图渲染.

        Args:
            sim_id: 仿真 id.
            kind: 网络类型, 当前支持 ``"interbank"`` / ``"cross_holdings"``.

        Returns:
            dict: ``projection.network_view()`` 输出 (nodes/edges).

        Raises:
            HTTPException: 404 仿真不存在或 kind 未知.
        """
        rs = _get(sim_id)
        with rs.lock:
            view = network_view(rs.state, kind)
        if view is None:
            raise HTTPException(
                404, f"未知网络类型: {kind}; 可用: interbank, cross_holdings"
            )
        return view

    @app.get("/api/sims/{sim_id}/stress")
    def stress(sim_id: str) -> dict:
        """压力测试指标 (银行违约率/资产缩幅/流动性缺口等).

        Args:
            sim_id: 仿真 id.

        Returns:
            dict: ``projection.stress_view()`` 输出.

        Raises:
            HTTPException: 404 仿真不存在.
        """
        rs = _get(sim_id)
        with rs.lock:
            return stress_view(rs.state)

    @app.get("/api/sims/{sim_id}/sfc")
    def sfc_detail(sim_id: str) -> dict:
        """SFC (Stock-Flow Consistent) 平衡细节, 含违约/不等式报告.

        Args:
            sim_id: 仿真 id.

        Returns:
            dict: ``projection.sfc_view()`` 输出, 含各主体账面恒等式余项.

        Raises:
            HTTPException: 404 仿真不存在.
        """
        rs = _get(sim_id)
        with rs.lock:
            return sfc_view(rs.state)

    @app.get("/api/meta")
    def meta() -> dict:
        """场景 + 冲击预设元数据 (前端不再硬编码副本)."""
        import yaml as _yaml

        scenarios_out = []
        for name in list_scenarios():
            path = (
                Path(__file__).resolve().parent.parent.parent
                / "scenarios" / f"{name}.yaml"
            )
            desc, disp = "", name
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = _yaml.safe_load(f) or {}
                desc = str(data.get("description", ""))
                disp = str(data.get("name", name))
            except OSError:
                pass
            scenarios_out.append(
                {"id": name, "name": disp, "description": desc}
            )
        return {
            "scenarios": scenarios_out,
            "shock_presets": [
                {
                    "id": pid,
                    "channel": cfg["channel"],
                    "magnitude": cfg["magnitude"],
                    "duration": cfg.get("duration", 1),
                    "one_shot": cfg.get("one_shot", True),
                    "description": PRESET_DESCRIPTIONS.get(pid, ""),
                }
                for pid, cfg in PRESET_SHOCKS.items()
            ],
            "custom_channels": CUSTOM_CHANNELS,
            "limits": {"max_sims": 8, "speed_range": [0, 60]},
        }

    @app.get("/api/sims/{sim_id}/interventions")
    def interventions(sim_id: str) -> list[dict]:
        """查询历史已施加的全部干预 (shock_log 快照).

        Args:
            sim_id: 仿真 id.

        Returns:
            list[dict]: ``projection.shock_log_view()`` 输出.

        Raises:
            HTTPException: 404 仿真不存在.
        """
        rs = _get(sim_id)
        with rs.lock:
            return shock_log_view(rs.state)

    # ── 干预网关 (W2: 唯一写通道) ──

    @app.post("/api/sims/{sim_id}/interventions")
    def add_intervention(sim_id: str, body: InterventionBody) -> dict:
        """干预网关 (W2): 唯一写通道, 接受预设或自定义通道构造 ShockEvent.

        必须满足其一: ``preset`` (推荐, 走 PRESET_SHOCKS) 或 ``channel``
        (白名单 CUSTOM_CHANNELS 之一). magnitude 缺省时取 preset 默认值.

        Args:
            sim_id: 仿真 id.
            body: ``{"preset"|"channel", magnitude, duration, one_shot, trigger_offset}``.

        Returns:
            dict: ``{"status": "accepted", trigger_t, channel, magnitude, shock_log_seq_hint}``.

        Raises:
            HTTPException: 404 仿真不存在; 422 缺 preset/channel 或参数非法.
        """
        rs = _get(sim_id)
        if body.preset is None and body.channel is None:
            raise HTTPException(422, "需要 preset 或 channel 之一")
        magnitude = body.magnitude
        if body.preset is not None:
            if body.preset not in PRESET_SHOCKS:
                raise HTTPException(
                    422, f"未知预设: {body.preset}; "
                         f"可用: {sorted(PRESET_SHOCKS)}"
                )
            if magnitude is None:
                magnitude = PRESET_SHOCKS[body.preset]["magnitude"]
            event = _make_event(
                body.preset, trigger_t=rs.state.t + body.trigger_offset,
                duration=body.duration, one_shot=body.one_shot,
                magnitude=magnitude,
            )
        else:
            assert body.channel is not None
            _validate_shock(body.channel, magnitude or 0.0)
            event = _make_event(
                f"ui_{body.channel}",
                trigger_t=rs.state.t + body.trigger_offset,
                duration=body.duration, one_shot=body.one_shot,
                magnitude=magnitude, channel_override=body.channel,
            )
        mgr = rs.state.event_manager
        if mgr is None:
            from financial_sim.simulation.events import EventManager
            rs.state.event_manager = EventManager([event])
        else:
            with rs.lock:
                mgr.events = list(getattr(mgr, "events", [])) + [event]
        seq = len(rs.state.shock_log)
        return {
            "status": "accepted",
            "trigger_t": event.trigger_t,
            "channel": event.channel,
            "magnitude": event.magnitude,
            "shock_log_seq_hint": seq,
        }

    # ── WebSocket tick 流 ──

    @app.websocket("/api/sims/{sim_id}/ws")
    async def ws_tick(websocket: WebSocket, sim_id: str) -> None:
        """WebSocket tick 流: 实时推送 macro_frame + 事件 + SFC 违规计数.

        双向协议:

        - 服务端主动推 ``{"type":"tick", t, macro, events_fired, sfc_violations, speed}``
          (~50ms 轮询, t 变化时发新帧).
        - 客户端可发 ``{"cmd": "set_speed"/"pause"/"step"/"run_to", ...}`` 控制播放,
          服务端回 ``{"type":"ack", cmd}``.

        Args:
            websocket: FastAPI WebSocket 连接.
            sim_id: 仿真 id; 不存在时关闭连接.
        """
        await websocket.accept()
        rs = registry.get(sim_id)
        if rs is None:
            await websocket.send_json({"type": "error",
                                       "message": "仿真不存在"})
            await websocket.close()
            return

        async def sender(sock: WebSocket) -> None:
            last_sent = -1
            while True:
                with rs.lock:
                    t = rs.state.t
                    new_frame_needed = t != last_sent
                    frame = None
                    if new_frame_needed:
                        last_sent = t
                        frame = {
                            "type": "tick",
                            "t": t,
                            "macro": macro_frame(rs.state),
                            "events_fired": [
                                e["name"] for e in rs.state.shock_log
                                if e.get("t") == t
                            ],
                            "sfc_violations": sum(
                                len(v)
                                for v in rs.state.sfc_violations
                            ),
                            "speed": rs.speed,
                        }
                if frame is not None:
                    await sock.send_json(frame)
                await asyncio.sleep(0.05)

        async def receiver(sock: WebSocket) -> None:
            try:
                while True:
                    msg = await sock.receive_json()
                    cmd = msg.get("cmd")
                    with rs.lock:
                        if cmd == "set_speed":
                            v = float(msg.get("value", 0))
                            if 0 <= v <= 60:
                                rs.speed = v
                                rs.run_to = None
                        elif cmd == "pause":
                            rs.speed = 0.0
                        elif cmd == "step":
                            rs.simulation.step()
                        elif cmd == "run_to":
                            rs.run_to = int(msg.get("t", rs.state.t))
                            rs.speed = max(rs.speed, 8.0)
                    await sock.send_json({"type": "ack", "cmd": cmd})
            except WebSocketDisconnect:
                return

        send_task = asyncio.create_task(sender(websocket))
        try:
            await receiver(websocket)
        finally:
            send_task.cancel()

    return app


def _yaml_cfg(text: str):
    """内联 YAML → SimConfig."""
    import yaml as _y

    from financial_sim.config import SimConfig
    data = _y.safe_load(text)
    return SimConfig(**data)


app = create_app()
