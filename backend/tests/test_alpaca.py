"""Bloco 3: Alpaca adapter (IEX feed) for the Time Machine and ORB backtests.

Everything here runs on the DERIVED fixture of tests/alpaca_fixtures.py (Yahoo bars from the
skill's file rewritten in Alpaca's format) and a fake HTTP layer. No test here proves that the
real Alpaca API behaves this way; the live smoke test at the end runs only with real keys and
DP_LIVE_ALPACA=1.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import os
import random
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from . import alpaca_fixtures as fx
from .conftest import DEMO, _reset, wait_job

SENTINEL_KEY = "PKALPACASENTINEL00000000"
SENTINEL_SECRET = "ALPACASECRETSENTINELneverShow000000000000"
NOW_1106 = fx.edt("2026-10-19", "11:06")   # data_end = 10:50 ET, same complete bars as the Yahoo file
PLAN = {"symbol": "TSLA", "date": "2026-10-19", "entry": 364.18, "stop": 358.32, "target": 370.04,
        "entry_time": "10:15", "replays": 10000, "seed": 19}


# ---------------------------------------------------------------- fixtures

@pytest.fixture()
def keys(settings_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_API_KEY_ID", SENTINEL_KEY)
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", SENTINEL_SECRET)
    _reset()


@pytest.fixture()
def fake(keys: None, monkeypatch: pytest.MonkeyPatch) -> fx.FakeAlpaca:
    from app.services import alpaca
    f = fx.FakeAlpaca(fx.derived_bars())
    monkeypatch.setattr(alpaca, "_http_get", f)
    monkeypatch.setattr(alpaca, "_now", lambda: NOW_1106)
    return f


@pytest.fixture()
def api(fake: fx.FakeAlpaca, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Demo lab, Alpaca keys set (auto -> Alpaca), Yahoo downloads forbidden (no silent switch)."""
    from app.main import create_app
    from app.services import market_data as md

    def no_yahoo(*a, **k):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("Yahoo must not be called when the 5-minute provider is Alpaca")

    monkeypatch.setattr(md, "fetch_chart_raw", no_yahoo)
    with TestClient(create_app()) as c:
        yield c


def _engine_doc(text: str, now_utc: dt.datetime) -> dict:
    from app.engines.runner import load_module
    tm = load_module("timemachine")
    plan = tm.normalize_plan({**PLAN, "side": "buy", "setup": "orb"})
    return tm.time_machine(text, plan, now_utc.replace(tzinfo=None), replays=10000, seed=19)


def _doc(bars: list[dict], window) -> str:  # noqa: ANN001
    from app.services import alpaca
    return alpaca.to_chart_document("TSLA", bars, window)


# ---------------------------------------------------------------- window on the NYSE calendar

def test_window_counts_sessions_and_stops_16_minutes_before_now(settings_env: Path) -> None:
    from app.services import alpaca
    w = alpaca.session_window(dt.date(2026, 10, 19), 20, NOW_1106)
    assert len(w.sessions) == 21 and w.sessions[-1] == dt.date(2026, 10, 19)
    assert w.sessions[0] == dt.date(2026, 9, 21)                      # 20 sessions before, no weekends
    assert w.start == fx.edt("2026-09-21", "09:30")
    assert w.data_end == fx.edt("2026-10-19", "10:50")                # 11:06 - 16 min = 10:50
    later = alpaca.session_window(dt.date(2026, 10, 16), 20, NOW_1106)
    assert later.data_end == fx.edt("2026-10-16", "16:00")            # a past day: its close


def test_window_skips_holidays_and_knows_early_closes(settings_env: Path) -> None:
    from app.services import alpaca
    now = fx.edt("2026-12-02", "18:00")
    w = alpaca.session_window(dt.date(2026, 12, 1), 20, now)
    assert dt.date(2026, 11, 26) not in w.sessions                    # Thanksgiving
    assert dt.date(2026, 11, 27) in w.sessions                        # 1 p.m. close
    with pytest.raises(alpaca.AlpacaError) as e:
        alpaca.session_window(dt.date(2026, 11, 26), 20, now)
    assert e.value.code == "market_closed"
    text = alpaca.to_chart_document("TSLA", [], w)
    q = {s["date"]: s for s in alpaca.session_quality(text)["incomplete_sessions"]}
    assert q["2026-11-27"]["expected"] == 42 and q["2026-11-27"]["early_close"] is True
    assert q["2026-11-30"]["expected"] == 78


def test_window_before_the_data_is_available(settings_env: Path) -> None:
    from app.services import alpaca
    with pytest.raises(alpaca.AlpacaError) as e:
        alpaca.session_window(dt.date(2026, 10, 19), 20, fx.edt("2026-10-19", "09:40"))
    assert e.value.code == "not_available_yet" and "15 minutos" in e.value.message
    with pytest.raises(alpaca.AlpacaError):
        alpaca.session_window(dt.date(2026, 10, 19), 19, NOW_1106)       # below 20
    with pytest.raises(alpaca.AlpacaError):
        alpaca.session_window(dt.date(2026, 10, 19), 251, NOW_1106)      # above 250


def test_backtest_window_ends_at_the_last_closed_session(settings_env: Path) -> None:
    from app.services import alpaca
    w = alpaca.session_window(None, 60, NOW_1106)                     # 10-19 still open at 10:50
    assert w.sessions[-1] == dt.date(2026, 10, 16) and len(w.sessions) == 60
    assert w.data_end == fx.edt("2026-10-16", "16:00")
    w2 = alpaca.session_window(None, 60, fx.edt("2026-10-19", "16:10"))
    assert w2.sessions[-1] == dt.date(2026, 10, 16)                   # 16:10 - 16 min -> 15:50: 10-19 not closed yet
    w3 = alpaca.session_window(None, 60, fx.edt("2026-10-19", "16:20"))
    assert w3.sessions[-1] == dt.date(2026, 10, 19)                   # 16:20 - 16 min -> 16:00: closed


# ---------------------------------------------------------------- conversion and deterministic JSON

GOLDEN_BARS = [
    {"t": "2026-10-16T13:30:00Z", "o": 100.0, "h": 101.5, "l": 99.25, "c": 101.0, "v": 1200, "n": 10, "vw": 100.4},
    {"t": "2026-10-16T13:35:00Z", "o": 101.0, "h": 102.0, "l": 100.5, "c": 101.75, "v": 800, "n": 7, "vw": 101.2},
    {"t": "2026-10-16T12:00:00Z", "o": 99.0, "h": 99.5, "l": 98.5, "c": 99.25, "v": 50, "n": 2, "vw": 99.1},   # 8:00 pre-market
    {"t": "2026-10-16T20:05:00Z", "o": 103.0, "h": 103.0, "l": 103.0, "c": 103.0, "v": 5, "n": 1, "vw": 103.0},  # after-hours
]


def _golden_window():  # noqa: ANN202
    from app.services import alpaca
    return alpaca.session_window(None, 20, fx.edt("2026-10-16", "18:00"))


def test_deterministic_json_with_fixed_data_and_metadata(settings_env: Path) -> None:
    from app.services import alpaca
    w = _golden_window()
    text = _doc(GOLDEN_BARS, w)
    # same bars in another order, other n/vw, and a later download: same text, same hash
    shuffled = [dict(b, n=999, vw=0.0) for b in GOLDEN_BARS]
    random.Random(3).shuffle(shuffled)
    assert _doc(shuffled, w) == text
    assert alpaca.to_chart_document("TSLA", copy.deepcopy(GOLDEN_BARS), alpaca.session_window(
        None, 20, fx.edt("2026-10-16", "23:59"))) == text                 # same window, other download time
    # any price, volume or window change changes the hash
    assert _doc([dict(GOLDEN_BARS[0], c=101.01), *GOLDEN_BARS[1:]], w) != text
    assert _doc([dict(GOLDEN_BARS[0], v=1201), *GOLDEN_BARS[1:]], w) != text
    assert _doc(GOLDEN_BARS, alpaca.session_window(None, 21, fx.edt("2026-10-16", "18:00"))) != text
    doc = json.loads(text)
    assert text == json.dumps(doc, separators=(",", ":"), sort_keys=True)  # canonical form
    meta = doc["chart"]["result"][0]["meta"]
    assert set(meta) == {"symbol", "dataGranularity", "exchangeTimezoneName", "currency", "regularMarketTime",
                         "dataProvider", "feed", "adjustment", "window", "leftOut"}
    assert "fetchedAt" not in text and "vw" not in text


def test_golden_hash_is_stable(settings_env: Path) -> None:
    """Pinned hash of the fixed input above. If this changes, every Alpaca snapshot's hash changes:
    only on purpose, with a note in docs/INTEGRACOES.md."""
    text = _doc(GOLDEN_BARS, _golden_window())
    assert hashlib.sha256(text.encode()).hexdigest() == PINNED_SHA, text


PINNED_SHA = "75b13b2aabad49ed7d994e681b28639a151ac5e89d75323af612417df6bbbf33"


def test_conversion_keeps_real_timestamps_and_marks_data_end(settings_env: Path) -> None:
    w = _golden_window()
    doc = json.loads(_doc(GOLDEN_BARS, w))
    r0 = doc["chart"]["result"][0]
    assert r0["timestamp"] == [int(fx.edt("2026-10-16", "09:30").timestamp()),
                               int(fx.edt("2026-10-16", "09:35").timestamp())]
    assert r0["meta"]["regularMarketTime"] == int(w.data_end.timestamp()) == int(fx.edt("2026-10-16", "16:00").timestamp())
    assert r0["meta"]["leftOut"] == {"outside_regular_hours": 2, "after_data_end": 0, "duplicate": 0}
    assert r0["meta"]["symbol"] == "TSLA" and r0["meta"]["dataGranularity"] == "5m"
    from app.services import alpaca
    brk = json.loads(alpaca.to_chart_document("BRK.B", [], w))["chart"]["result"][0]["meta"]["symbol"]
    assert brk == "BRK-B"  # the engines compare Yahoo-style symbols


def test_bars_at_or_after_data_end_are_not_kept(settings_env: Path) -> None:
    from app.services import alpaca
    w = alpaca.session_window(dt.date(2026, 10, 19), 20, NOW_1106)
    bars = [{"t": fx.rfc3339(int(fx.edt("2026-10-19", hm).timestamp())), "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}
            for hm in ("10:40", "10:45", "10:50", "10:55")]
    doc = json.loads(alpaca.to_chart_document("TSLA", bars, w))["chart"]["result"][0]
    assert [fx.rfc3339(t) for t in doc["timestamp"]] == [bars[0]["t"], bars[1]["t"]]
    assert doc["meta"]["leftOut"]["after_data_end"] == 2
    # the engine treats exactly those two as complete (regularMarketTime = data_end, not the download time)
    from app.engines.runner import load_module
    tm = load_module("timemachine")
    _, parsed, dropped = tm.parse_bars(doc, dt.datetime(2030, 1, 1))
    assert [b["start"] for b in parsed] == ["10:40", "10:45"] and dropped["not_complete"] == 0


# ---------------------------------------------------------------- same engine result as the Yahoo file

def test_derived_fixture_gives_the_same_time_machine_result_seed_19(fake: fx.FakeAlpaca) -> None:
    from app.services import alpaca
    text, _, quality = alpaca.fetch_session_chart("TSLA", dt.date(2026, 10, 19), 60)
    a = _engine_doc(text, NOW_1106)
    y = _engine_doc(fx.yahoo_text(), fx.edt("2026-10-19", "10:50"))
    for k in ("plan", "mc", "history", "verdict", "verdict_notes", "warnings", "note"):
        assert a[k] == y[k], k
    assert a["data"]["last_bar"] == y["data"]["last_bar"] == "2026-10-19 10:40 ET"
    assert a["mc"]["pool_sessions"] == 59 == quality["pool_sessions"]
    assert a["mc"]["p_target"] == y["mc"]["p_target"]


# ---------------------------------------------------------------- pagination, quota, errors

def test_pagination_follows_next_page_token_and_spends_one_call_per_page(fake: fx.FakeAlpaca) -> None:
    from app.services import alpaca, providers
    fake.page_size = 700
    w = alpaca.session_window(dt.date(2026, 10, 19), 60, NOW_1106)
    bars = alpaca.fetch_bars("TSLA", "5Min", w.start, w.data_end - dt.timedelta(seconds=1))
    assert len(bars) == len(fx.derived_bars()) and len(fake.calls) == -(-len(bars) // 700)
    assert [c.get("page_token") for c in fake.calls][:3] == [None, "700", "1400"]
    c0 = fake.calls[0]
    assert (c0["feed"], c0["adjustment"], c0["timeframe"], c0["limit"], c0["sort"]) == ("iex", "all", "5Min", 10000, "asc")
    assert c0["end"] == "2026-10-19T14:49:59Z"                         # inclusive end: 1 s before data_end
    usage = {p["id"]: p["usage"] for p in providers.status()}["alpaca"]
    assert usage["minute"] == len(fake.calls)


def test_quota_refusal_stops_the_download(fake: fx.FakeAlpaca, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import alpaca, providers
    monkeypatch.setitem(providers.PROVIDERS, "alpaca", providers.PROVIDERS["alpaca"].__class__(
        **{**providers.PROVIDERS["alpaca"].__dict__, "per_minute": 2}))
    fake.page_size = 500
    with pytest.raises(alpaca.AlpacaError) as e:
        alpaca.fetch_session_chart("TSLA", dt.date(2026, 10, 19), 60)
    assert e.value.code == "rate_limited" and len(fake.calls) == 2


def test_headers_carry_the_keys_and_nothing_else_does(keys: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import alpaca
    seen = {}

    def transport(request: httpx.Request) -> httpx.Response:
        seen["headers"], seen["url"] = dict(request.headers), str(request.url)
        return httpx.Response(200, json={"bars": {}, "next_page_token": None})

    monkeypatch.setattr(alpaca.httpx, "get", lambda *a, **k: httpx.Client(transport=httpx.MockTransport(transport)).get(*a, **k))
    alpaca.fetch_bars("TSLA", "5Min", fx.edt("2026-10-16", "09:30"), fx.edt("2026-10-16", "15:59"))
    assert seen["headers"]["apca-api-key-id"] == SENTINEL_KEY
    assert seen["headers"]["apca-api-secret-key"] == SENTINEL_SECRET
    assert SENTINEL_KEY not in seen["url"] and SENTINEL_SECRET not in seen["url"]


@pytest.mark.parametrize(("status", "body", "code"), [
    (401, {"message": "unauthorized"}, "provider_auth"),
    (403, {"message": "forbidden"}, "provider_auth"),
    (429, {"message": "too many requests"}, "rate_limited"),
    (400, {"message": f"invalid key {SENTINEL_KEY} / {SENTINEL_SECRET}"}, "provider_bad_request"),
    (500, {"message": "internal"}, "provider_error"),
])
def test_http_errors_are_mapped_and_scrubbed(keys: None, monkeypatch: pytest.MonkeyPatch, status: int, body: dict,
                                             code: str) -> None:
    from app.services import alpaca, providers
    monkeypatch.setattr(alpaca, "_http_get", fx.FakeAlpaca([], status=status, body=body))
    with pytest.raises(alpaca.AlpacaError) as e:
        alpaca.fetch_bars("TSLA", "5Min", fx.edt("2026-10-16", "09:30"), fx.edt("2026-10-16", "15:59"))
    assert e.value.code == code
    text = f"{e.value} {e.value.message} {e.value!r}"
    assert SENTINEL_KEY not in text and SENTINEL_SECRET not in text
    if status == 429:
        st = {p["id"]: p for p in providers.status()}["alpaca"]
        assert st["status_code"] == "provider_paused"


@pytest.mark.parametrize(("exc", "code"), [
    (httpx.ConnectError(f"cannot reach https://data.alpaca.markets/?k={SENTINEL_KEY}"), "provider_unreachable"),
    (httpx.ReadTimeout("timed out"), "provider_timeout"),
])
def test_network_errors_never_echo_the_request(keys: None, monkeypatch: pytest.MonkeyPatch, exc: Exception,
                                               code: str) -> None:
    from app.services import alpaca
    monkeypatch.setattr(alpaca, "_http_get", fx.FakeAlpaca([], exc=exc))
    with pytest.raises(alpaca.AlpacaError) as e:
        alpaca.fetch_bars("TSLA", "5Min", fx.edt("2026-10-16", "09:30"), fx.edt("2026-10-16", "15:59"))
    assert e.value.code == code and SENTINEL_KEY not in str(e.value) and "data.alpaca" not in str(e.value)


def test_without_keys_the_provider_is_refused(settings_env: Path) -> None:
    from app.services import alpaca
    with pytest.raises(alpaca.AlpacaError) as e:
        alpaca.fetch_bars("TSLA", "5Min", fx.edt("2026-10-16", "09:30"), fx.edt("2026-10-16", "15:59"))
    assert e.value.code == "missing_key"


# ---------------------------------------------------------------- IEX gaps: measured, never filled

def _bars_without(drop: dict[str, list[str]]) -> list[dict]:
    out = []
    for b in fx.derived_bars():
        local = dt.datetime.fromisoformat(b["t"].replace("Z", "+00:00")).astimezone(fx.NY)
        if local.strftime("%H:%M") in drop.get(local.date().isoformat(), []) or drop.get(local.date().isoformat()) == ["*"]:
            continue
        out.append(b)
    return out


def test_gaps_are_counted_and_sessions_left_out(fake: fx.FakeAlpaca) -> None:
    from app.services import alpaca
    fake.bars = _bars_without({"2026-10-14": ["11:00", "11:05"], "2026-10-15": ["15:55"]})
    text, _, q = alpaca.fetch_session_chart("TSLA", dt.date(2026, 10, 19), 60)
    inc = {s["date"]: s for s in q["incomplete_sessions"]}
    assert inc["2026-10-14"]["missing"] == 2 and inc["2026-10-14"]["missing_times"] == ["11:00", "11:05"]
    assert inc["2026-10-15"]["bars"] == 77 and inc["2026-10-15"]["state"] == "closed"
    assert q["pool_sessions"] == 57 and q["filled"] is False
    # the plan's day is in progress, not "incomplete"
    ip = q["in_progress_session"]
    assert ip["date"] == "2026-10-19" and ip["state"] == "in_progress" and ip["expected"] == 16 and ip["bars"] == 15
    assert "2026-10-19" not in inc
    # nothing was filled: the engine sees the same gaps
    r0 = json.loads(text)["chart"]["result"][0]
    assert len(r0["timestamp"]) == len(fake.bars)
    assert _engine_doc(text, NOW_1106)["mc"]["pool_sessions"] == 57


def test_in_progress_bars_missing_by_the_delay_are_not_gaps(fake: fx.FakeAlpaca, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import alpaca
    early = fx.edt("2026-10-19", "10:20")                              # data_end 10:00
    monkeypatch.setattr(alpaca, "_now", lambda: early)
    text, _, q = alpaca.fetch_session_chart("TSLA", dt.date(2026, 10, 19), 60)
    assert q["in_progress_session"]["expected"] == 6 and q["in_progress_session"]["missing"] == 0
    msg = alpaca.entry_bar_check(text, dt.date(2026, 10, 19), "10:15")
    assert msg and "ainda não estava disponível" in msg and "15 minutos" in msg


def test_missing_entry_bar_gets_a_clear_reason(fake: fx.FakeAlpaca) -> None:
    from app.services import alpaca
    fake.bars = _bars_without({"2026-10-19": ["10:10"]})
    text, _, _ = alpaca.fetch_session_chart("TSLA", dt.date(2026, 10, 19), 60)
    msg = alpaca.entry_bar_check(text, dt.date(2026, 10, 19), "10:15")
    assert "não tem candle das 10:10" in msg and "não preenche" in msg
    assert alpaca.entry_bar_check(text, dt.date(2026, 10, 19), "10:20") is None


# ---------------------------------------------------------------- API end to end (fake Alpaca)

def test_time_machine_end_to_end_with_alpaca(api: TestClient, fake: fx.FakeAlpaca) -> None:
    # reference numbers from the skill's own file
    snaps = api.get("/api/snapshots?symbol=TSLA&interval=5m", headers=DEMO).json()
    ref_snap = [s for s in snaps if s["is_fixture"]][0]["id"]
    r = api.post("/api/timemachine", json={**PLAN, "snapshot_id": ref_snap}, headers=DEMO).json()
    assert wait_job(api, r["job"]["id"])["status"] == "succeeded"
    ref = api.get(f"/api/experiments/{r['experiment_id']}", headers=DEMO).json()["results"]

    r = api.post("/api/timemachine", json={**PLAN, "history_sessions": 60}, headers=DEMO).json()
    j = wait_job(api, r["job"]["id"])
    assert j["status"] == "succeeded", j.get("error")
    e = api.get(f"/api/experiments/{r['experiment_id']}", headers=DEMO).json()
    res = e["results"]
    assert res["mc"] == ref["mc"] and res["history"] == ref["history"] and res["verdict"] == ref["verdict"]
    snap = res["snapshot"]
    assert snap["source"] == "alpaca:iex" and snap["is_fixture"] is False
    assert snap["provenance"]["provider"] == "alpaca" and snap["provenance"]["feed"] == "iex"
    q = res["data_quality"]
    assert q["feed"] == "iex" and q["pool_sessions"] == 59 and q["in_progress_session"]["date"] == "2026-10-19"
    assert any("IEX" in x for x in res["limitations"])
    row = [s for s in api.get("/api/snapshots?symbol=TSLA&interval=5m", headers=DEMO).json() if s["id"] == snap["id"]][0]
    assert row["range"] == "60sess" and row["source"] == "alpaca:iex"
    assert row["fetched_at"].startswith("2026-10-19T15:06")

    # reproduce from the frozen snapshot: no new download, same numbers, same hash and quality
    calls = len(fake.calls)
    r2 = api.post("/api/timemachine", json={**PLAN, "snapshot_id": snap["id"], "seed": 19, "replays": 10000},
                  headers=DEMO).json()
    assert wait_job(api, r2["job"]["id"])["status"] == "succeeded"
    res2 = api.get(f"/api/experiments/{r2['experiment_id']}", headers=DEMO).json()["results"]
    assert len(fake.calls) == calls
    assert res2["mc"] == res["mc"] and res2["snapshot"]["sha256"] == snap["sha256"]
    assert res2["data_quality"] == q

    sess = api.get(f"/api/snapshots/{snap['id']}/sessions", headers=DEMO).json()
    assert sess["data_quality"]["pool_sessions"] == 59
    body = json.dumps(e) + json.dumps(sess)
    assert SENTINEL_KEY not in body and SENTINEL_SECRET not in body


def test_orb_backtest_end_to_end_with_alpaca(api: TestClient, fake: fx.FakeAlpaca) -> None:
    cfg = {"symbol": "TSLA", "rule": {"type": "orb", "params": {"or_minutes": 15}},
           "exit": {"stop_type": "or_mid", "target_r": 2, "flat_by": "16:00"}}
    s = api.post("/api/strategies", json={"name": "ORB Alpaca", "config": cfg}, headers=DEMO)
    assert s.status_code in (200, 201), s.text
    sid = s.json()["id"]
    snaps = api.get("/api/snapshots?symbol=TSLA&interval=5m", headers=DEMO).json()
    ref_snap = [x for x in snaps if x["is_fixture"]][0]["id"]
    ref = api.post("/api/backtests", json={"strategy_id": sid, "snapshot_id": ref_snap}, headers=DEMO).json()
    assert wait_job(api, ref["job"]["id"])["status"] == "succeeded"
    ref_res = api.get(f"/api/experiments/{ref['experiment_id']}", headers=DEMO).json()

    r = api.post("/api/backtests", json={"strategy_id": sid, "history_sessions": 60}, headers=DEMO).json()
    j = wait_job(api, r["job"]["id"])
    assert j["status"] == "succeeded", j.get("error")
    e = api.get(f"/api/experiments/{r['experiment_id']}", headers=DEMO).json()
    res = e["results"]
    assert res["snapshot"]["source"] == "alpaca:iex"
    assert res["data_quality"]["sessions"] == 60 and res["data_quality"]["in_progress_session"] is None
    assert res["sessions"] == ref_res["results"]["sessions"] == 59
    strip = lambda ts: [{k: v for k, v in t.items() if k not in ("id", "experiment_id", "created_at")} for t in ts]  # noqa: E731
    assert strip(e["trades"]) == strip(ref_res["trades"])


def test_history_sessions_is_validated(api: TestClient) -> None:
    for n in (19, 251):
        r = api.post("/api/timemachine", json={**PLAN, "history_sessions": n}, headers=DEMO)
        assert r.status_code == 422


def test_alpaca_failure_does_not_switch_to_yahoo(api: TestClient, fake: fx.FakeAlpaca) -> None:
    fake.status, fake.body = 500, {"message": "boom"}
    r = api.post("/api/timemachine", json=PLAN, headers=DEMO).json()
    j = wait_job(api, r["job"]["id"])          # the api fixture makes any Yahoo call an AssertionError
    assert j["status"] == "failed" and "Alpaca respondeu HTTP 500" in (j.get("error") or "")
    e = api.get(f"/api/experiments/{r['experiment_id']}", headers=DEMO).json()
    assert e["status"] == "failed" and "Alpaca" in e["error"]


def test_entry_bar_gap_and_short_history_fail_with_reasons(api: TestClient, fake: fx.FakeAlpaca) -> None:
    fake.bars = _bars_without({"2026-10-19": ["10:10"]})
    r = api.post("/api/timemachine", json=PLAN, headers=DEMO).json()
    j = wait_job(api, r["job"]["id"])
    assert j["status"] == "failed" and "não tem candle das 10:10" in j["error"]
    # 45 of the 59 sessions with one missing bar: only 14 complete ones left
    drop = {}
    for b in fx.derived_bars():
        d = b["t"][:10]
        if d < "2026-10-19":
            drop.setdefault(d, ["12:00"])
    keep = sorted(drop)[-14:]
    fake.bars = _bars_without({d: v for d, v in drop.items() if d not in keep})
    r = api.post("/api/timemachine", json={**PLAN, "history_sessions": 61}, headers=DEMO).json()
    j = wait_job(api, r["job"]["id"])
    assert j["status"] == "failed" and "Só 14 sessões completas" in j["error"] and "precisa de 20" in j["error"]


def test_provider_choice_by_configuration(settings_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import config
    from app.services import providers
    assert providers.bars_provider("5m") == "yahoo"                    # auto, no keys
    monkeypatch.setenv("ALPACA_API_KEY_ID", SENTINEL_KEY)
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", SENTINEL_SECRET)
    config.get_settings.cache_clear()
    assert providers.bars_provider("5m") == "alpaca"                   # auto, keys
    assert providers.bars_provider("1d") == "yahoo"                    # daily bars stay on Yahoo
    monkeypatch.setenv("DP_INTRADAY_PROVIDER", "yahoo")
    config.get_settings.cache_clear()
    assert providers.bars_provider("5m") == "yahoo"
    monkeypatch.setenv("DP_INTRADAY_PROVIDER", "")
    config.get_settings.cache_clear()
    assert providers.bars_provider("5m") == "alpaca"                   # blank = auto


def test_forced_alpaca_without_key_is_refused_up_front(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import config
    monkeypatch.setenv("DP_INTRADAY_PROVIDER", "alpaca")
    config.get_settings.cache_clear()
    r = client.post("/api/timemachine", json=PLAN, headers=DEMO)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "missing_key"


def test_daily_backtest_stays_on_yahoo_and_its_policy(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import config
    cfg = {"symbol": "TSLA", "rule": {"type": "breakout_20d"}, "exit": {"stop_type": "pct", "stop_value": 3}}
    sid = api.post("/api/strategies", json={"name": "Diária", "config": cfg}, headers=DEMO).json()["id"]
    monkeypatch.setenv("DP_ALLOW_UNOFFICIAL_SOURCES", "false")
    config.get_settings.cache_clear()
    r = api.post("/api/backtests", json={"strategy_id": sid}, headers=DEMO)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "source_disabled"


# ---------------------------------------------------------------- check_alpaca.py never shows the keys

def test_check_script_never_prints_any_part_of_the_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                        capsys: pytest.CaptureFixture[str]) -> None:
    import importlib.util
    import io
    import urllib.request
    path = Path(__file__).resolve().parents[2] / "scripts" / "check_alpaca.py"
    spec = importlib.util.spec_from_file_location("check_alpaca", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    key, secret = "PKQXkeyfragmentJWYZ", "qvSECRETfragmentXKJW"   # no digits: parts cannot match the output by chance
    monkeypatch.setattr(mod, "read_env", lambda: {"ALPACA_API_KEY_ID": key, "ALPACA_API_SECRET_KEY": secret})
    day = "2026-10-16"
    bars = [{"t": fx.rfc3339(int(fx.edt(day, f"{9 + (30 + 5 * i) // 60:02d}:{(30 + 5 * i) % 60:02d}").timestamp())),
             "o": 1, "h": 1, "l": 1, "c": 1, "v": 1} for i in range(78)]

    class R(io.BytesIO):
        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, *a):  # noqa: ANN002, ANN204
            return False

    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=0: R(json.dumps({"bars": {"TSLA": bars}}).encode()))
    monkeypatch.setattr("sys.argv", ["check_alpaca.py", "--date", day])
    assert mod.main() == 0
    out = capsys.readouterr().out
    for part in (key, secret, key[:2], key[-2:], secret[:2], secret[-2:]):
        assert part not in out, part
    assert "OK: 78 barras" in out and "início da barra" in out


# ---------------------------------------------------------------- live smoke test (real keys only)

def _env_file_keys() -> dict[str, str]:
    vals = {}
    for p in (Path(__file__).resolve().parents[1] / ".env", Path(__file__).resolve().parents[2] / ".env"):
        if p.exists():
            for line in p.read_text(encoding="utf-8-sig").splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.split("=", 1)
                    vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


@pytest.mark.skipif(os.environ.get("DP_LIVE_ALPACA") != "1", reason="teste real: defina DP_LIVE_ALPACA=1 e as chaves")
def test_live_alpaca_smoke(settings_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    keys_found = {k: os.environ.get("LIVE_" + k) or _env_file_keys().get(k, "")
                  for k in ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY")}
    if not all(keys_found.values()):
        pytest.skip("sem ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY em backend/.env")
    for k, v in keys_found.items():
        monkeypatch.setenv(k, v)
    _reset()
    from app.services import alpaca
    text, _, q = alpaca.fetch_session_chart("SPY", None, 20)
    r0 = json.loads(text)["chart"]["result"][0]
    first = dt.datetime.fromtimestamp(r0["timestamp"][0], alpaca.mcal.NY)
    assert first.strftime("%H:%M") == "09:30", "t não é o início da barra?"
    assert q["sessions"] == 20 and q["closed_sessions"] == 20
    for v in keys_found.values():
        assert v not in text
