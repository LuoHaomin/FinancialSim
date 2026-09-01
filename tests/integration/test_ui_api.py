"""Phase 4 W1/W2: FastAPI 服务层冒烟 + 干预网关测试."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from financial_sim.ui_service.main import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def _mk_sim(client: TestClient, scenario: str = "baseline",
            **overrides) -> str:
    body = {
        "scenario": scenario,
        "autostart_speed": 0,       # 测试用暂停模式, 手动 step 保证确定性
        "overrides": {"n_households": 100, "n_ticks": 200, **overrides},
    }
    r = client.post("/api/sims", json=body)
    assert r.status_code == 200, r.text
    return r.json()["sim_id"]


class TestLifecycle:
    def test_create_and_meta(self, client):
        sim_id = _mk_sim(client)
        meta = client.get(f"/api/sims/{sim_id}").json()
        assert meta["name"] == "baseline"
        assert meta["t"] == 0
        assert meta["sfc_violations"] == 0

    def test_step_advances_and_series(self, client):
        sim_id = _mk_sim(client)
        r = client.post(f"/api/sims/{sim_id}/command",
                        json={"step": 12})
        assert r.json()["t"] == 12
        series = client.get(
            f"/api/sims/{sim_id}/series", params={"from_t": 0}
        ).json()
        # ⚠️ 标签语义: macro_history 在 t 自增**前**写入 →
        # 跑 12 步后快照标签为 0..11 (帧 = "第 t 月月初状态")
        assert len(series["t"]) == 12
        assert series["t"][-1] == 11
        # 列对齐
        for key in ("real_gdp", "inflation_yoy", "unemployment_rate"):
            assert len(series[key]) == len(series["t"])

    def test_unknown_sim_404(self, client):
        assert client.get("/api/sims/nope").status_code == 404

    def test_close(self, client):
        sim_id = _mk_sim(client)
        assert client.delete(f"/api/sims/{sim_id}").json()["closed"]
        assert client.get(f"/api/sims/{sim_id}").status_code == 404

    def test_max_sims_cap_409(self, client):
        ids = []
        try:
            from financial_sim.ui_service.registry import MAX_SIMS
            for _ in range(MAX_SIMS):
                ids.append(_mk_sim(client))
            r = client.post("/api/sims", json={
                "scenario": "baseline", "autostart_speed": 0,
                "overrides": {"n_households": 20},
            })
            assert r.status_code == 409
        finally:
            for i in ids:
                client.delete(i)

    def test_list(self, client):
        sim_id = _mk_sim(client)
        metas = client.get("/api/sims").json()
        assert any(m["sim_id"] == sim_id for m in metas)


class TestProjection:
    def test_firms_table(self, client):
        sim_id = _mk_sim(client)
        rows = client.get(f"/api/sims/{sim_id}/agents/firms").json()
        assert rows
        assert "sector" in rows[0]

    def test_banks_table(self, client):
        sim_id = _mk_sim(client)
        rows = client.get(f"/api/sims/{sim_id}/agents/banks").json()
        assert rows
        assert {"capital", "car"} <= set(rows[0])

    def test_agent_detail_not_found(self, client):
        sim_id = _mk_sim(client)
        r = client.get(f"/api/sims/{sim_id}/agent/firms/nonexistent")
        assert r.status_code == 404


class TestInterventionGateway:
    """W2 验收: 干预唯一写通道; 全部落 shock_log; 非法输入不入账."""

    def test_intervention_enters_shock_log(self, client):
        sim_id = _mk_sim(client)
        # t=0 注入加息 → 推进到触发点
        r = client.post(f"/api/sims/{sim_id}/interventions", json={
            "preset": "tightening_50bp_6m", "trigger_offset": 3,
        })
        assert r.status_code == 200
        assert r.json()["trigger_t"] == 3
        client.post(f"/api/sims/{sim_id}/command", json={"step": 5})
        log = client.get(f"/api/sims/{sim_id}/interventions").json()
        entries = [e for e in log if e["name"] == "tightening_50bp_6m"]
        assert entries
        assert entries[0]["t"] == 3

    def test_rate_change_visible_in_series(self, client):
        sim_id = _mk_sim(client, n_ticks=50)
        client.post(f"/api/sims/{sim_id}/interventions", json={
            "preset": "tightening_50bp_6m", "trigger_offset": 2,
        })
        client.post(f"/api/sims/{sim_id}/command", json={"step": 10})
        series = client.get(
            f"/api/sims/{sim_id}/series"
        ).json()
        # 冲击后政策利率应被扰动 (不强校准方向, 只验证传导发生)
        assert any(abs(v - 0.025) > 1e-9 for v in series["policy_rate"])

    def test_unknown_preset_422(self, client):
        sim_id = _mk_sim(client)
        r = client.post(f"/api/sims/{sim_id}/interventions",
                        json={"preset": "meteor_strike"})
        assert r.status_code == 422

    def test_illegal_magnitude_422(self, client):
        sim_id = _mk_sim(client)
        r = client.post(f"/api/sims/{sim_id}/interventions", json={
            "channel": "policy_rate", "magnitude": 99,
        })
        assert r.status_code == 422
        # 不入账
        assert client.get(f"/api/sims/{sim_id}/interventions").json() == []

    def test_custom_channel_accepted(self, client):
        sim_id = _mk_sim(client)
        r = client.post(f"/api/sims/{sim_id}/interventions", json={
            "channel": "policy_rate", "magnitude": 0.01,
            "trigger_offset": 1,
        })
        assert r.status_code == 200
        assert r.json()["channel"] == "policy_rate"


class TestWebSocket:
    def test_tick_stream_and_commands(self, client):
        sim_id = _mk_sim(client)
        with client.websocket_connect(
            f"/api/sims/{sim_id}/ws"
        ) as ws:
            frames = []
            while len(frames) < 1:
                msg = ws.receive_json()
                if msg.get("type") == "tick":
                    frames.append(msg)
            ws.send_json({"cmd": "step"})
            acked = False
            while not acked:
                msg = ws.receive_json()
                if msg.get("type") == "ack":
                    acked = True
            ws.send_json({"cmd": "set_speed", "value": 0})
            # 两条 ack 之后应出现带新 t 的 tick 帧 (端到端命令→推送闭环)
            saw_new_tick = False
            for _ in range(10):
                msg = ws.receive_json()
                if (
                    msg.get("type") == "tick" and msg["t"] >= 1
                ):
                    saw_new_tick = True
                    break
                # 其余为 ack 帧, 继续读
            assert saw_new_tick


class TestDeterminism:
    def test_same_seed_same_history_through_api(self, client):
        histories = []
        for _ in range(2):
            sim_id = _mk_sim(client)
            client.post(f"/api/sims/{sim_id}/interventions", json={
                "preset": "tightening_50bp_6m", "trigger_offset": 2,
            })
            client.post(f"/api/sims/{sim_id}/command", json={"step": 15})
            s = client.get(f"/api/sims/{sim_id}/series").json()
            histories.append((s["t"], s["real_gdp"], s["policy_rate"]))
        assert histories[0] == histories[1]


class TestExtendedProjections:
    """Phase A 扩展投影端点: 部门矩阵 / 家庭分布 / 政府央行 / 网络 / 压力 / SFC."""

    def test_meta_endpoint(self, client):
        meta = client.get("/api/meta").json()
        ids = [s["id"] for s in meta["scenarios"]]
        assert "baseline" in ids
        assert "crisis_2008" in ids
        presets = {p["id"] for p in meta["shock_presets"]}
        assert "rate_hike_100bp" in presets
        assert "policy_rate" in meta["custom_channels"]

    def test_sectors_matrix_balanced(self, client):
        sim_id = _mk_sim(client)
        client.post(f"/api/sims/{sim_id}/command", json={"step": 3})
        r = client.get(f"/api/sims/{sim_id}/sectors")
        assert r.status_code == 200
        sectors = r.json()["sectors"]
        # 基础 5 部门必须存在 (NBFI 可选)
        for name in ("households", "firms", "banks", "government", "cb"):
            assert name in sectors
            s = sectors[name]
            assert abs(
                s["total_assets"] - s["total_liabilities"] - s["net_worth"]
            ) < 1e-3 * max(1.0, abs(s["total_assets"]))
            assert s["balanced"]

    def test_households_stats(self, client):
        sim_id = _mk_sim(client)
        client.post(f"/api/sims/{sim_id}/command", json={"step": 3})
        st = client.get(f"/api/sims/{sim_id}/households").json()
        assert st["n"] == 100
        assert 0 <= st["gini_wealth"] <= 1
        assert len(st["wealth_quintiles"]) == 5
        # 分位数均值单调不减 (数值容差内)
        q = st["wealth_quintiles"]
        assert all(q[i] <= q[i + 1] + 1e-9 for i in range(4))
        assert 0 <= st["homeownership_rate"] <= 1

    def test_government_and_cb_views(self, client):
        sim_id = _mk_sim(client)
        client.post(f"/api/sims/{sim_id}/command", json={"step": 2})
        gov = client.get(f"/api/sims/{sim_id}/agents/government").json()
        assert "bonds_outstanding" in gov["liabilities"]
        assert "income_tax_rate" in gov["parameters"]
        cb = client.get(
            f"/api/sims/{sim_id}/agents/central_bank"
        ).json()
        assert "bank_reserves" in cb["liabilities"]
        assert "policy_rate" in cb["policy"]
        assert cb["monetary_base"] > 0

    def test_interbank_network_shape(self, client):
        sim_id = _mk_sim(client, n_banks=5)
        client.post(f"/api/sims/{sim_id}/command", json={"step": 2})
        net = client.get(
            f"/api/sims/{sim_id}/network/interbank"
        ).json()
        assert net["kind"] == "interbank"
        ids = {n["id"] for n in net["nodes"]}
        assert len(ids) == 5
        for e in net["edges"]:
            assert e["source"] in ids
            assert e["target"] in ids
            assert e["value"] > 0
        # 未知类型 404
        assert client.get(
            f"/api/sims/{sim_id}/network/friendship"
        ).status_code == 404

    def test_stress_view(self, client):
        sim_id = _mk_sim(client)
        client.post(f"/api/sims/{sim_id}/command", json={"step": 3})
        st = client.get(f"/api/sims/{sim_id}/stress").json()
        assert 0 <= st["fire_sale_pressure"] <= 1
        assert st["bank_car"]["mean"] is not None
        assert st["housing"]["price"] > 0

    def test_sfc_view_zero_when_clean(self, client):
        sim_id = _mk_sim(client)
        client.post(f"/api/sims/{sim_id}/command", json={"step": 5})
        sfc = client.get(f"/api/sims/{sim_id}/sfc").json()
        assert sfc["total_count"] == 0
        assert sfc["detail"] == []

    def test_series_extended_keys(self, client):
        sim_id = _mk_sim(client)
        client.post(f"/api/sims/{sim_id}/command", json={"step": 6})
        s = client.get(f"/api/sims/{sim_id}/series").json()
        for key in ("nominal_gdp", "avg_wage", "total_consumption",
                    "total_output", "housing_price", "price_level"):
            assert len(s[key]) == len(s["t"])
        # 对齐后不应有 None (历史同步追加)
        assert all(v is not None for v in s["price_level"])
