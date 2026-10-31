"""Bloco 4: the ORB plan (trader-entry + trader-exit) from the plan day's own bars.

The reference numbers come from the skill's own tests on its TSLA file (2026-10-19): range
354.47-362.18, the 10:10 bar closes 364.18 -> entry at 10:15; or-mid stop 358.32, 1R target
370.04; atr:1.5 stop 359.35 (ATR 3.2182 over 9 bars), 2R target 373.84 (tests/test_exit.py).

Alpaca is a fake HTTP layer serving the DERIVED fixture of tests/alpaca_fixtures.py (Yahoo bars
rewritten in Alpaca's format). Nothing here proves how the real Alpaca API behaves.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from . import alpaca_fixtures as fx
from .conftest import DEMO, _reset
from .test_policy import _fixture_snapshot, public_default  # noqa: F401  (fixture reused below)

SENTINEL_KEY = "PKPLANSENTINEL000000000"
SENTINEL_SECRET = "PLANSECRETSENTINELneverShow0000000000000"
NOW_1106 = fx.edt("2026-10-19", "11:06")   # data_end 10:50 ET: the same complete bars as the skill's file
DAY = {"symbol": "TSLA", "date": "2026-10-19", "or_minutes": 15}
REEL = (364.18, 358.32, 370.04, "10:15")


@pytest.fixture()
def alpaca_api(settings_env: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, fx.FakeAlpaca]]:
    """Demo lab, Alpaca keys set (auto -> Alpaca, feed SIP), Yahoo forbidden (no silent switch)."""
    monkeypatch.setenv("ALPACA_API_KEY_ID", SENTINEL_KEY)
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", SENTINEL_SECRET)
    _reset()
    from app.main import create_app
    from app.services import alpaca
    from app.services import market_data as md
    fake = fx.FakeAlpaca(fx.derived_bars())
    monkeypatch.setattr(alpaca, "_http_get", fake)
    monkeypatch.setattr(alpaca, "_now", lambda: NOW_1106)

    def no_yahoo(*a, **k):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("Yahoo must not be called when the 5-minute provider is Alpaca")

    monkeypatch.setattr(md, "fetch_chart_raw", no_yahoo)
    with TestClient(create_app()) as c:
        yield c, fake


def _plan(r: dict) -> tuple:
    p = r["plan"]
    return p["entry"], p["stop"], p["target"], p["entry_time"]


# ---------------------------------------------------------------- from a snapshot (as before)

def test_snapshot_plan_is_unchanged_and_says_where_its_data_came_from(client: TestClient) -> None:
    snap = _fixture_snapshot(client, DEMO)
    r = client.post("/api/plan/orb", json={"snapshot_id": snap, "date": "2026-10-19", "target_r": 1},
                    headers=DEMO).json()
    assert r["triggered"] is True and _plan(r) == REEL
    assert r["snapshot"]["id"] == snap and r["snapshot"]["is_fixture"] is True
    assert r["snapshot"]["provenance"]["provider"] == "yahoo" and r["data_quality"] is None
    # the file was saved live at 10:49 ET: the plan is evaluated as of then, not at 16:05
    assert r["evaluated_at"].startswith("2026-10-19 10:4")


def test_atr_stop_matches_the_exit_engine_reference(client: TestClient) -> None:
    snap = _fixture_snapshot(client, DEMO)
    r = client.post("/api/plan/orb", json={"snapshot_id": snap, "date": "2026-10-19", "stop_rule": "atr",
                                           "atr_k": 1.5, "target_r": 2}, headers=DEMO).json()
    p = r["plan"]
    assert (p["entry"], p["stop"], p["risk_per_share"], p["target"]) == (364.18, 359.35, 4.83, 373.84)
    assert p["atr_bars"] == 9 and abs(p["atr"] - 3.2182) < 1e-4 and p["atr_k"] == 1.5
    assert p["stop_rule"] == "atr" and "ATR(9)" in p["stop_label"]
    assert any("ATR" in n for n in r["notes"])


# ---------------------------------------------------------------- from the day's own bars (Alpaca)

def test_plan_downloads_only_the_plan_day_and_freezes_it(alpaca_api: tuple[TestClient, fx.FakeAlpaca]) -> None:
    c, fake = alpaca_api
    r = c.post("/api/plan/orb", json={**DAY, "target_r": 1}, headers=DEMO)
    assert r.status_code == 200, r.text
    r = r.json()
    assert r["triggered"] is True and _plan(r) == REEL
    assert len(fake.calls) == 1
    q = fake.calls[0]
    assert (q["feed"], q["start"], q["end"]) == ("sip", "2026-10-19T13:30:00Z", "2026-10-19T14:49:59Z")
    snap = r["snapshot"]
    assert snap["source"] == "alpaca:sip" and snap["range"] == "1sess" and snap["is_fixture"] is False
    assert snap["provenance"]["provider"] == "alpaca" and snap["provenance"]["feed"] == "sip"
    dq = r["data_quality"]
    assert dq["sessions"] == 1 and dq["sessions_requested"] == 0
    # 9:30 to 10:40: the derived file has no 10:45 bar (the skill's file was saved at 10:49:45)
    assert dq["in_progress_session"]["date"] == "2026-10-19" and dq["in_progress_session"]["bars"] == 15
    assert r["evaluated_at"] == "2026-10-19 10:50 ET"
    # frozen like any other snapshot, and the same bars reuse the same row
    rows = [s for s in c.get("/api/snapshots?symbol=TSLA&interval=5m", headers=DEMO).json() if s["id"] == snap["id"]]
    assert rows and rows[0]["source"] == "alpaca:sip"
    again = c.post("/api/plan/orb", json={**DAY, "target_r": 1}, headers=DEMO).json()
    assert again["snapshot"]["id"] == snap["id"] and _plan(again) == REEL
    # ... and the plan can be recomputed from that snapshot without any download
    calls = len(fake.calls)
    frozen = c.post("/api/plan/orb", json={"snapshot_id": snap["id"], "date": "2026-10-19", "target_r": 1},
                    headers=DEMO).json()
    assert _plan(frozen) == REEL and len(fake.calls) == calls
    body = json.dumps(r) + json.dumps(again)
    assert SENTINEL_KEY not in body and SENTINEL_SECRET not in body


def test_atr_stop_from_alpaca_bars_matches_the_reference(alpaca_api: tuple[TestClient, fx.FakeAlpaca]) -> None:
    c, _ = alpaca_api
    r = c.post("/api/plan/orb", json={**DAY, "stop_rule": "atr", "atr_k": 1.5, "target_r": 2}, headers=DEMO).json()
    p = r["plan"]
    assert (p["entry"], p["stop"], p["target"], p["atr_bars"]) == (364.18, 359.35, 373.84, 9)


def test_session_still_open_reads_as_waiting_not_expired(alpaca_api: tuple[TestClient, fx.FakeAlpaca],
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """At 10:16 ET the Basic plan serves bars up to 10:00: the range is set, no close above it
    yet. Evaluated at 16:05 this would read 'expired'; at the data's own time it is 'waiting'."""
    c, _ = alpaca_api
    from app.services import alpaca
    monkeypatch.setattr(alpaca, "_now", lambda: fx.edt("2026-10-19", "10:16"))
    r = c.post("/api/plan/orb", json=DAY, headers=DEMO).json()
    assert r["triggered"] is False and r["status"] == "waiting", r
    assert r["opening_range"]["high"] == 362.18 and r["evaluated_at"] == "2026-10-19 10:00 ET"


def test_atr_stop_refused_with_fewer_than_three_bars(alpaca_api: tuple[TestClient, fx.FakeAlpaca]) -> None:
    """With the default no_entries_before (9:45) the trigger always has 3 bars behind it; gaps in
    the feed can still leave fewer. Here only the 9:40 range bar and the 10:10 trigger bar exist."""
    c, fake = alpaca_api
    gone = {"09:30", "09:35", "09:45", "09:50", "09:55", "10:00", "10:05"}
    fake.bars = [b for b in fake.bars if not (b["t"].startswith("2026-10-19")
                 and dt.datetime.fromisoformat(b["t"].replace("Z", "+00:00")).astimezone(fx.NY).strftime("%H:%M") in gone)]
    r = c.post("/api/plan/orb", json={**DAY, "stop_rule": "atr"}, headers=DEMO).json()
    assert r["triggered"] is True and r["trigger"]["bar_index"] == 8
    assert r["plan"] is None and "pelo menos 3 candles" in r["refusal"] and "há 2" in r["refusal"]
    assert r["data_quality"]["in_progress_session"]["missing"] >= 7


def test_entry_engine_failure_and_missing_bars(alpaca_api: tuple[TestClient, fx.FakeAlpaca],
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    c, fake = alpaca_api
    from app.services import alpaca
    monkeypatch.setattr(alpaca, "_now", lambda: fx.edt("2026-10-19", "09:40"))
    r = c.post("/api/plan/orb", json=DAY, headers=DEMO)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "not_available_yet"
    monkeypatch.setattr(alpaca, "_now", lambda: NOW_1106)
    fake.bars = []
    r = c.post("/api/plan/orb", json=DAY, headers=DEMO)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "no_data"


def test_alpaca_errors_do_not_switch_to_yahoo(alpaca_api: tuple[TestClient, fx.FakeAlpaca]) -> None:
    c, fake = alpaca_api
    fake.status, fake.body = 401, {"message": f"bad key {SENTINEL_KEY}"}
    r = c.post("/api/plan/orb", json=DAY, headers=DEMO)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "provider_auth"
    assert SENTINEL_KEY not in r.text and SENTINEL_SECRET not in r.text


def test_requests_are_validated(alpaca_api: tuple[TestClient, fx.FakeAlpaca]) -> None:
    c, _ = alpaca_api
    assert c.post("/api/plan/orb", json={"date": "2026-10-19"}, headers=DEMO).status_code == 422
    for bad in ({"atr_k": 0.1}, {"atr_k": 11}, {"stop_rule": "chandelier"}, {"symbol": "TOOLONG"},
                {"date": "2099-01-02"}):
        assert c.post("/api/plan/orb", json={**DAY, **bad}, headers=DEMO).status_code == 422, bad
    r = c.post("/api/plan/orb", json={**DAY, "date": "2026-09-07"}, headers=DEMO)   # Labor Day
    assert r.status_code == 422 and r.json()["detail"]["code"] == "market_closed"
    snap = _fixture_snapshot(c, DEMO)
    r = c.post("/api/plan/orb", json={**DAY, "symbol": "NVDA", "snapshot_id": snap}, headers=DEMO)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "symbol_mismatch"


# ---------------------------------------------------------------- Yahoo as the 5-minute provider

def test_yahoo_provider_uses_the_shortest_range(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import day_bars
    from app.services import market_data as md
    seen = []

    doc = json.loads(fx.yahoo_text())
    doc["chart"]["result"][0]["meta"]["test_copy"] = True   # not byte-identical to the reference file
    text = json.dumps(doc)

    def fake_yahoo(symbol, rng, interval, use_cache=True):  # noqa: ANN001, ANN202
        seen.append((symbol, rng, interval, use_cache))
        return text, dt.datetime(2026, 10, 19, 14, 50, tzinfo=dt.UTC), False

    monkeypatch.setattr(md, "fetch_chart_raw", fake_yahoo)
    monkeypatch.setattr(day_bars, "yahoo_range", lambda day, today: "60d")
    r = client.post("/api/plan/orb", json={**DAY, "target_r": 1}, headers=DEMO).json()
    assert _plan(r) == REEL and r["snapshot"]["source"] == "yahoo" and r["snapshot"]["range"] == "60d"
    assert seen == [("TSLA", "60d", "5m", False)]


def test_yahoo_range_rule(settings_env: Path) -> None:
    from app.services import day_bars
    today = dt.date(2026, 10, 30)
    assert day_bars.yahoo_range(today, today) == "1d"
    assert day_bars.yahoo_range(dt.date(2026, 10, 26), today) == "5d"
    assert day_bars.yahoo_range(dt.date(2026, 9, 15), today) == "60d"
    with pytest.raises(day_bars.DayBarsError):
        day_bars.yahoo_range(dt.date(2026, 7, 1), today)


# ---------------------------------------------------------------- display policy (public lab)

@pytest.fixture()
def public_alpaca(public_default: TestClient,  # noqa: F811
                  monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, fx.FakeAlpaca]:
    from app.services import alpaca
    fake = fx.FakeAlpaca(fx.derived_bars())
    monkeypatch.setattr(alpaca, "_http_get", fake)
    monkeypatch.setattr(alpaca, "_now", lambda: NOW_1106)
    return public_default, fake


def test_public_lab_shows_provider_plans_in_r(public_alpaca: tuple[TestClient, fx.FakeAlpaca],
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    c, fake = public_alpaca
    r = c.post("/api/plan/orb", json={**DAY, "target_r": 1})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["prices_hidden"] is True and body["triggered"] is True
    p = body["plan"]
    assert not {"entry", "stop", "target", "risk_per_share", "stop_detail"} & set(p)
    assert (p["entry_r"], p["stop_r"], p["target_r"], p["entry_time"]) == (0.0, -1.0, 1.0, "10:15")
    assert abs(p["stop_pct"] - 100 * (358.32 - 364.18) / 364.18) < 1e-3
    assert abs(p["target_pct"] - 100 * (370.04 - 364.18) / 364.18) < 1e-3
    assert "high" not in body["opening_range"] and body["opening_range"]["high_pct"] < 0
    assert "price" not in body["trigger"] and "close" not in body["trigger"]
    assert body["plan_rule"]["stop_rule"] == "or_mid"
    for price in ("364.18", "358.32", "370.04", "362.18", "354.47"):
        assert price not in r.text, price
    # the package's reference file keeps its dollars
    snap = _fixture_snapshot(c)
    ok = c.post("/api/plan/orb", json={"snapshot_id": snap, "date": "2026-10-19", "target_r": 1}).json()
    assert ok["prices_hidden"] is False and _plan(ok) == REEL
    # switched on explicitly by the operator
    monkeypatch.setenv("DP_SHOW_TRIGGER_PRICES", "true")
    from app import config
    config.get_settings.cache_clear()
    r = c.post("/api/plan/orb", json={**DAY, "target_r": 1})
    assert r.status_code == 200 and _plan(r.json()) == REEL


def test_public_time_machine_runs_on_the_server_plan_and_shows_r(public_alpaca: tuple[TestClient, fx.FakeAlpaca]) -> None:
    """The whole public flow: plan rule -> Time Machine on the server -> results, trades, job,
    list and export in R, with no provider price anywhere in the API."""
    from .conftest import wait_job
    c, fake = public_alpaca
    rule = {"or_minutes": 15, "stop_rule": "or_mid", "target_r": 1}
    r = c.post("/api/timemachine", json={"symbol": "TSLA", "date": "2026-10-19", "plan_rule": rule,
                                         "replays": 2000, "seed": 19, "history_sessions": 60})
    assert r.status_code == 202, r.text
    r = r.json()
    j = wait_job(c, r["job"]["id"], headers={})
    assert j["status"] == "succeeded", j.get("error")
    e = c.get(f"/api/experiments/{r['experiment_id']}")
    res = e.json()["results"]
    assert res["prices_hidden"] is True and res["display_note"]
    assert res["plan"]["entry_r"] == 0.0 and res["plan"]["stop_r"] == -1.0 and "entry" not in res["plan"]
    mc = res["mc"]
    assert mc["unit"] == "R" and "median_close" not in mc and isinstance(mc["median_close_r"], float)
    assert all(x == 0.0 for x in mc["bands"][0])                   # every band starts at the entry
    assert all(path[0] == 0.0 for path in mc["sample_paths"])
    trades = e.json()["trades"]
    assert trades and all(t["entry"] is None and t["stop"] is None and t["r_multiple"] is not None for t in trades)
    job = c.get(f"/api/jobs/{r['job']['id']}").json()
    lst = c.get("/api/experiments").json()
    csv = c.get(f"/api/experiments/{r['experiment_id']}/export?format=csv").text
    js = c.get(f"/api/experiments/{r['experiment_id']}/export?format=json").text
    assert csv.splitlines()[0] == "symbol,source,dataset,entry_date,entry_time,exit_date,outcome,r_multiple"
    for price in ("364.18", "358.32", "370.04"):
        for name, text in (("experiment", e.text), ("job", json.dumps(job)), ("list", json.dumps(lst)),
                           ("csv", csv), ("json", js)):
            assert price not in text, (name, price)


def test_server_plan_gives_the_same_run_as_the_priced_plan(client: TestClient) -> None:
    """Demo lab, reference file: plan_rule computes 364.18 / 358.32 / 370.04 at 10:15 on the server,
    so the Monte Carlo is identical to the run with those prices typed in."""
    from .conftest import wait_job
    snap = _fixture_snapshot(client, DEMO)
    base = {"symbol": "TSLA", "date": "2026-10-19", "replays": 2000, "seed": 19, "snapshot_id": snap}
    a = client.post("/api/timemachine", json={**base, "entry": 364.18, "stop": 358.32, "target": 370.04,
                                              "entry_time": "10:15"}, headers=DEMO).json()
    b = client.post("/api/timemachine", json={**base, "plan_rule": {"stop_rule": "or_mid", "target_r": 1}},
                    headers=DEMO).json()
    assert wait_job(client, a["job"]["id"])["status"] == "succeeded"
    assert wait_job(client, b["job"]["id"])["status"] == "succeeded"
    ra = client.get(f"/api/experiments/{a['experiment_id']}", headers=DEMO).json()["results"]
    rb = client.get(f"/api/experiments/{b['experiment_id']}", headers=DEMO).json()["results"]
    assert ra["mc"] == rb["mc"] and ra["history"] == rb["history"]
    assert (rb["plan"]["entry"], rb["plan"]["stop"], rb["plan"]["target"]) == (364.18, 358.32, 370.04)
    pb = client.get(f"/api/experiments/{b['experiment_id']}", headers=DEMO).json()["params"]
    assert "entry" not in pb and pb["plan_rule"]["stop_rule"] == "or_mid"


def test_time_machine_request_needs_prices_or_a_rule(client: TestClient) -> None:
    base = {"symbol": "TSLA", "date": "2026-10-19"}
    assert client.post("/api/timemachine", json=base, headers=DEMO).status_code == 422
    both = {**base, "entry": 364.18, "stop": 358.32, "target": 370.04, "entry_time": "10:15",
            "plan_rule": {"stop_rule": "or_mid"}}
    assert client.post("/api/timemachine", json=both, headers=DEMO).status_code == 422
    partial = {**base, "entry": 364.18, "stop": 358.32}
    assert client.post("/api/timemachine", json=partial, headers=DEMO).status_code == 422


def test_server_plan_that_does_not_trigger_fails_with_the_reason(alpaca_api: tuple[TestClient, fx.FakeAlpaca],
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import alpaca

    from .conftest import wait_job
    c, _ = alpaca_api
    monkeypatch.setattr(alpaca, "_now", lambda: fx.edt("2026-10-19", "10:16"))   # data up to 10:00: no trigger yet
    r = c.post("/api/timemachine", json={"symbol": "TSLA", "date": "2026-10-19", "plan_rule": {},
                                         "replays": 500}, headers=DEMO).json()
    j = wait_job(c, r["job"]["id"])
    assert j["status"] == "failed" and "não disparou" in (j.get("error") or "")
