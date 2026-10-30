from __future__ import annotations

import datetime as dt
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient

from .conftest import DEMO, wait_job

REF_PLAN = {"symbol": "TSLA", "date": "2026-10-19", "entry": 364.18, "stop": 358.32, "target": 370.04,
            "entry_time": "10:15", "replays": 10000, "seed": 19}


def fixture_snapshot(client: TestClient) -> str:
    snaps = client.get("/api/snapshots?symbol=TSLA&interval=5m", headers=DEMO).json()
    fx = [s for s in snaps if s["is_fixture"]]
    assert fx, "the demo bootstrap registers the skill's TSLA file"
    return fx[0]["id"]


# ---------------------------------------------------------------- basics and auth

def test_health_reports_engines_and_no_broker(client: TestClient) -> None:
    h = client.get("/api/health").json()
    assert h["status"] == "ok"
    assert h["broker"] == "not_integrated"
    assert set(h["engines"].values()) == {"ok"}


def test_demo_is_loopback_only(client: TestClient) -> None:
    """The local demo no longer has a login screen: loopback requests get the demo workspace,
    a wrong token is still refused, and nothing outside the machine is accepted."""
    for path in ("/api/me", "/api/strategies", "/api/dashboard", "/api/journal", "/api/experiments"):
        assert client.get(path).status_code == 200
        assert client.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401
    from fastapi.testclient import TestClient as TC
    remote = TC(client.app, client=("203.0.113.9", 5555))
    assert remote.get("/api/me").status_code == 401


def test_me_and_workspace(client: TestClient) -> None:
    me = client.get("/api/me", headers=DEMO).json()
    assert me["workspace"]["is_demo"] is True
    ws = client.get("/api/workspace", headers=DEMO).json()
    assert len(ws["members"]) == 1


def test_no_order_routes_exist(client: TestClient) -> None:
    paths = [r.path for r in client.app.routes]
    assert not [p for p in paths if "order" in p or "broker" in p or "trade/place" in p]


def test_broker_module_is_not_vendored() -> None:
    from app.config import get_settings
    assert not (get_settings().dp_skill_dir / "trader-broker").exists()


# ---------------------------------------------------------------- supabase JWT mode

@pytest.fixture()
def supa(tmp_path, monkeypatch):  # noqa: ANN001, ANN201
    monkeypatch.setenv("DP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DP_AUTH_MODE", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret-test-secret-test-secret-123")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + (tmp_path / "s.sqlite").as_posix())
    from app import config, db
    config.get_settings.cache_clear()
    db.reset_engine()
    db.create_demo_schema()
    a, b = uuid.uuid4(), uuid.uuid4()
    wa, wb = uuid.uuid4(), uuid.uuid4()
    with db.get_engine().begin() as conn:
        for uid, wid, email in ((a, wa, "a@test"), (b, wb, "b@test")):
            conn.execute(db.profiles.insert().values(id=uid, email=email, display_name=email, preferences={}))
            conn.execute(db.workspaces.insert().values(id=wid, name="ws-" + email, is_demo=False, settings={}))
            conn.execute(db.workspace_members.insert().values(workspace_id=wid, user_id=uid, role="owner"))
    from app.main import create_app
    with TestClient(create_app()) as c:
        yield c, a, b
    config.get_settings.cache_clear()
    db.reset_engine()


def token(sub: uuid.UUID, **over) -> str:  # noqa: ANN003
    claims = {"sub": str(sub), "aud": "authenticated", "role": "authenticated", "email": "x@test",
              "iss": "https://example.supabase.co/auth/v1",
              "exp": dt.datetime.now(dt.UTC) + dt.timedelta(minutes=5), **over}
    return jwt.encode(claims, "test-secret-test-secret-test-secret-123", algorithm="HS256")


def test_supabase_jwt_verification(supa) -> None:  # noqa: ANN001
    c, a, _ = supa
    ok = c.get("/api/me", headers={"Authorization": f"Bearer {token(a)}"})
    assert ok.status_code == 200 and ok.json()["id"] == str(a)
    assert c.get("/api/me", headers={"Authorization": "Bearer demo-local"}).status_code == 401
    expired = token(a, exp=dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1))
    assert c.get("/api/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    assert c.get("/api/me", headers={"Authorization": f"Bearer {token(a, aud='other')}"}).status_code == 401
    assert c.get("/api/me", headers={"Authorization": f"Bearer {token(a, iss='https://evil/auth/v1')}"}).status_code == 401
    forged = jwt.encode({"sub": str(a), "aud": "authenticated", "role": "authenticated"}, "x" * 40, algorithm="HS256")
    assert c.get("/api/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    stranger = c.get("/api/me", headers={"Authorization": f"Bearer {token(uuid.uuid4())}"})
    assert stranger.status_code == 403 and stranger.json()["detail"]["code"] == "not_a_member"


def test_workspaces_are_isolated(supa) -> None:  # noqa: ANN001
    c, a, b = supa
    ha, hb = {"Authorization": f"Bearer {token(a)}"}, {"Authorization": f"Bearer {token(b)}"}
    cfg = {"symbol": "AAPL", "rule": {"type": "breakout_20d"}, "exit": {"stop_type": "pct", "stop_value": 3}}
    sid = c.post("/api/strategies", json={"name": "Privada A", "config": cfg}, headers=ha).json()["id"]
    assert c.get(f"/api/strategies/{sid}", headers=hb).status_code == 404
    assert c.patch(f"/api/strategies/{sid}", json={"name": "hack"}, headers=hb).status_code == 404
    assert c.delete(f"/api/strategies/{sid}", headers=hb).status_code == 404
    assert c.get("/api/strategies", headers=hb).json() == []
    assert c.get(f"/api/strategies/{sid}", headers=ha).status_code == 200


# ---------------------------------------------------------------- validation

@pytest.mark.parametrize("patch,field", [
    ({"stop": 370.0}, "stop"), ({"target": 360.0}, "target"), ({"entry_time": "10:17"}, "entry_time"),
    ({"symbol": "TSLA; rm -rf"}, "symbol"), ({"replays": 10**7}, "replays"), ({"date": "2099-01-01"}, "date"),
    ({"extra_field": 1}, "extra"),
])
def test_time_machine_rejects_bad_input(client: TestClient, patch: dict, field: str) -> None:
    r = client.post("/api/timemachine", json={**REF_PLAN, **patch}, headers=DEMO)
    assert r.status_code == 422, field
    assert r.json()["detail"]["code"] == "validation_error"


# ---------------------------------------------------------------- time machine regression

def test_time_machine_reference_run_is_reproducible(client: TestClient) -> None:
    snap = fixture_snapshot(client)
    results = []
    for _ in range(2):
        r = client.post("/api/timemachine", json={**REF_PLAN, "snapshot_id": snap}, headers=DEMO)
        assert r.status_code == 202, r.text
        job = wait_job(client, r.json()["job"]["id"])
        assert job["status"] == "succeeded", job
        e = client.get(f"/api/experiments/{r.json()['experiment_id']}", headers=DEMO).json()
        results.append(e)
    mc = results[0]["results"]["mc"]
    assert (mc["p_target"], mc["p_stop"], mc["p_neither"], mc["p_green"]) == (0.2938, 0.2548, 0.4514, 0.5168)
    assert (mc["median_close"], mc["p5_close"], mc["p95_close"], mc["avg_R"]) == (364.36, 355.54, 373.54, 0.034)
    assert mc["pool_sessions"] == 59 and mc["seed"] == 19 and mc["replays"] == 10000
    h = results[0]["results"]["history"]
    assert (h["triggered"], h["target"], h["stop"], h["close"], h["avg_R"]) == (33, 13, 15, 5, -0.062)
    assert len(results[0]["trades"]) == 33
    assert results[0]["results"]["mc"] == results[1]["results"]["mc"]
    sim = results[0]["simulation"]
    assert sim["seed"] == 19 and len(sim["snapshot_sha256"]) == 64 and sim["pool_sessions"] == 59
    hs = results[0]["results"]["history_summary"]
    assert hs["trades"] == 33 and hs["sample"] == "ok"
    lo, hi = hs["win_rate_ci95"]
    assert hi - lo > 0.3, "33 trades leave a wide interval around the win rate"


def test_time_machine_without_data_fails_cleanly(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import market_data as md

    def down(*_a, **_k):  # noqa: ANN002, ANN003, ANN202
        raise md.DataError("provider_unreachable", "Não foi possível acessar o provedor de dados.")

    monkeypatch.setattr(md, "fetch_chart_raw", down)
    r = client.post("/api/timemachine", json={**REF_PLAN, "symbol": "NVDA", "entry": 10, "stop": 9, "target": 11},
                    headers=DEMO)
    job = wait_job(client, r.json()["job"]["id"])
    assert job["status"] == "failed" and "provedor" in job["error"]
    e = client.get(f"/api/experiments/{r.json()['experiment_id']}", headers=DEMO).json()
    assert e["status"] == "failed" and e["results"] is None and e["trades"] == []


def test_time_machine_entry_bar_missing_is_refused(client: TestClient) -> None:
    snap = fixture_snapshot(client)
    r = client.post("/api/timemachine", json={**REF_PLAN, "date": "2026-01-05", "snapshot_id": snap}, headers=DEMO)
    job = wait_job(client, r.json()["job"]["id"])
    assert job["status"] == "failed" and job["error"]


# ---------------------------------------------------------------- strategies, backtests, analytics

ORB_CFG = {"symbol": "TSLA", "rule": {"type": "orb", "params": {"or_minutes": 15}},
           "exit": {"stop_type": "or_mid", "target_r": 1, "flat_by": "16:00"}}


def test_strategy_versions_duplicate_and_delete(client: TestClient) -> None:
    s = client.post("/api/strategies", json={"name": "ORB teste", "config": ORB_CFG}, headers=DEMO).json()
    assert s["current_version"] == 1
    same = client.patch(f"/api/strategies/{s['id']}", json={"config": ORB_CFG}, headers=DEMO).json()
    assert same["current_version"] == 1, "unchanged config does not create a version"
    cfg2 = {**ORB_CFG, "exit": {**ORB_CFG["exit"], "target_r": 2}}
    v2 = client.patch(f"/api/strategies/{s['id']}", json={"config": cfg2, "note": "alvo 2R"}, headers=DEMO).json()
    assert v2["current_version"] == 2 and [v["version"] for v in v2["versions"]] == [2, 1]
    dup = client.post(f"/api/strategies/{s['id']}/duplicate", headers=DEMO).json()
    assert dup["id"] != s["id"] and dup["name"].endswith("(cópia)")
    assert client.delete(f"/api/strategies/{dup['id']}", headers=DEMO).status_code == 204
    assert client.get(f"/api/strategies/{dup['id']}", headers=DEMO).status_code == 404


def test_invalid_strategy_combinations(client: TestClient) -> None:
    bad = {**ORB_CFG, "exit": {"stop_type": "atr", "stop_value": 2}}
    assert client.post("/api/strategies", json={"name": "x1", "config": bad}, headers=DEMO).status_code == 422
    bad2 = {"symbol": "AAPL", "rule": {"type": "sma_cross", "params": {"fast": 50, "slow": 20}}}
    assert client.post("/api/strategies", json={"name": "x2", "config": bad2}, headers=DEMO).status_code == 422
    bad3 = {"symbol": "AAPL", "rule": {"type": "oversold", "params": {"made_up": 1}}}
    assert client.post("/api/strategies", json={"name": "x3", "config": bad3}, headers=DEMO).status_code == 422


def test_orb_backtest_matches_time_machine_history_and_analytics(client: TestClient) -> None:
    snap = fixture_snapshot(client)
    s = client.post("/api/strategies", json={"name": "ORB ref", "config": ORB_CFG}, headers=DEMO).json()
    r = client.post("/api/backtests", json={"strategy_id": s["id"], "snapshot_id": snap,
                                            "split_date": "2026-09-15"}, headers=DEMO)
    assert r.status_code == 202, r.text
    job = wait_job(client, r.json()["job"]["id"])
    assert job["status"] == "succeeded", job
    e = client.get(f"/api/experiments/{r.json()['experiment_id']}", headers=DEMO).json()
    res = e["results"]
    assert res["sessions"] >= 59 and res["summary"]["all"]["trades"] == len(e["trades"])
    assert {t["dataset"] for t in e["trades"]} <= {"development", "out_of_sample"}
    dev, oos = res["summary"]["development"]["trades"], res["summary"]["out_of_sample"]["trades"]
    assert dev + oos == len(e["trades"])
    a = client.get(f"/api/analytics?experiment_id={e['id']}&dataset=out_of_sample", headers=DEMO).json()
    assert a["summary"]["trades"] == oos
    csv_text = client.get(f"/api/experiments/{e['id']}/export?format=csv", headers=DEMO).text
    assert csv_text.splitlines()[0].startswith("symbol,source,dataset") and len(csv_text.splitlines()) == len(e["trades"]) + 1
    assert client.get(f"/api/experiments/{e['id']}/export?format=json", headers=DEMO).json()["experiment"]["id"] == e["id"]


def test_duplicate_runs_are_deduplicated(client: TestClient) -> None:
    snap = fixture_snapshot(client)
    body = {**REF_PLAN, "snapshot_id": snap, "replays": 50000}
    r1 = client.post("/api/timemachine", json=body, headers=DEMO).json()
    r2 = client.post("/api/timemachine", json=body, headers=DEMO).json()
    if r1["job"]["status"] in ("queued", "running") and r2["created"] is False:
        assert r1["job"]["id"] == r2["job"]["id"]
    wait_job(client, r1["job"]["id"])
    wait_job(client, r2["job"]["id"])


def test_cancel_a_running_job(client: TestClient) -> None:
    snap = fixture_snapshot(client)
    r = client.post("/api/timemachine", json={**REF_PLAN, "snapshot_id": snap, "replays": 50000, "seed": 7},
                    headers=DEMO).json()
    client.post(f"/api/jobs/{r['job']['id']}/cancel", headers=DEMO)
    job = wait_job(client, r["job"]["id"])
    assert job["status"] in ("cancelled", "succeeded")
    if job["status"] == "cancelled":
        e = client.get(f"/api/experiments/{r['experiment_id']}", headers=DEMO).json()
        assert e["status"] == "cancelled"


# ---------------------------------------------------------------- replay

def test_replay_sessions_and_bars(client: TestClient) -> None:
    snap = fixture_snapshot(client)
    s = client.get(f"/api/snapshots/{snap}/sessions", headers=DEMO).json()
    assert any(x["date"] == "2026-10-19" for x in s["sessions"])
    b = client.get(f"/api/snapshots/{snap}/bars?date=2026-10-19", headers=DEMO).json()
    times = [x["time"] for x in b["bars"]]
    assert times == sorted(times) and b["bars"][0]["et"] == "09:30"


# ---------------------------------------------------------------- risk, journal, watchlists

def test_simulated_risk_check(client: TestClient) -> None:
    r = client.post("/api/risk/check", json={"symbol": "TSLA", "date": "2026-10-19", "entry": 364.18,
                                             "stop": 358.32, "target": 370.04, "entry_time": "10:15",
                                             "risk": {"account_size": 5000, "max_loss_per_trade": 50,
                                                      "max_position_pct": 75}},
                    headers=DEMO).json()
    assert r["simulated"] is True
    assert r["sizing"]["qty"] == 8 and r["sizing"]["bound_by"] == "max loss"  # the skill's own example
    capped = client.post("/api/risk/check", json={"symbol": "TSLA", "date": "2026-10-19", "entry": 364.18,
                                                  "stop": 358.32, "target": 370.04, "entry_time": "10:15",
                                                  "risk": {"account_size": 5000, "max_loss_per_trade": 50,
                                                           "max_position_pct": 50}}, headers=DEMO).json()
    assert capped["sizing"]["qty"] == 6 and capped["sizing"]["bound_by"] == "position cap"


def test_journal_crud_search_and_attachment(client: TestClient) -> None:
    e = client.post("/api/journal", json={"title": "Hipótese ORB", "body": "Testar ORB em dias de gap.",
                                          "kind": "hypothesis", "symbol": "tsla", "tags": ["ORB", "gap"]},
                    headers=DEMO).json()
    assert e["symbol"] == "TSLA" and e["tags"] == ["gap", "orb"]
    found = client.get("/api/journal?q=gap", headers=DEMO).json()
    assert [x["id"] for x in found] == [e["id"]] and found[0]["author_name"]
    assert client.get("/api/journal?tag=orb", headers=DEMO).json()[0]["id"] == e["id"]
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    up = client.post(f"/api/journal/{e['id']}/attachments", files={"file": ("chart.png", png, "image/png")},
                     headers=DEMO)
    assert up.status_code == 201, up.text
    assert client.get(f"/api/attachments/{up.json()['id']}", headers=DEMO).content == png
    fake = client.post(f"/api/journal/{e['id']}/attachments", files={"file": ("x.png", b"<svg/>", "image/png")},
                       headers=DEMO)
    assert fake.status_code == 400
    upd = client.put(f"/api/journal/{e['id']}", json={"title": "Hipótese ORB v2", "tags": []}, headers=DEMO)
    assert upd.json()["title"] == "Hipótese ORB v2"
    assert client.delete(f"/api/journal/{e['id']}", headers=DEMO).status_code == 204
    assert client.get(f"/api/attachments/{up.json()['id']}", headers=DEMO).status_code == 404


def test_watchlist_flow(client: TestClient) -> None:
    w = client.post("/api/watchlists", json={"name": "Teste"}, headers=DEMO).json()
    assert client.post(f"/api/watchlists/{w['id']}/assets", json={"symbol": "nvda"}, headers=DEMO).status_code == 201
    dup = client.post(f"/api/watchlists/{w['id']}/assets", json={"symbol": "NVDA"}, headers=DEMO)
    assert dup.status_code == 400
    lst = [x for x in client.get("/api/watchlists", headers=DEMO).json() if x["id"] == w["id"]][0]
    assert [a["symbol"] for a in lst["assets"]] == ["NVDA"]
    assert client.delete(f"/api/watchlists/{w['id']}/assets/NVDA", headers=DEMO).status_code == 204


def test_orb_plan_from_entry_and_exit_engines(client: TestClient) -> None:
    snap = fixture_snapshot(client)
    r = client.post("/api/plan/orb", json={"snapshot_id": snap, "date": "2026-10-19", "or_minutes": 15,
                                           "stop_rule": "or_mid", "target_r": 1}, headers=DEMO).json()
    assert r["triggered"] is True, r
    p = r["plan"]
    # the reel: range 354.47-362.18, the 10:10 bar closes 364.18 -> entry at 10:15, stop 358.32, target 370.04
    assert (r["opening_range"]["high"], r["opening_range"]["low"]) == (362.18, 354.47)
    assert (p["entry"], p["stop"], p["target"], p["entry_time"]) == (364.18, 358.32, 370.04, "10:15")
