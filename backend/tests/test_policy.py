"""Display policy, provider status, shared quotas and provenance (Bloco 2)."""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from .conftest import DEMO, _reset, wait_job

SENTINEL_KEY = "PKSENTINELKEY0000000000"
SENTINEL_SECRET = "SENTINELSECRETnevershow0000000000000000000"
PLAN = {"symbol": "TSLA", "date": "2026-10-19", "entry": 364.18, "stop": 358.32, "target": 370.04,
        "entry_time": "10:15", "replays": 500, "seed": 19}


@pytest.fixture()
def public_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """The public lab with the policy left at its defaults (nothing set in the environment)."""
    monkeypatch.setenv("DP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("SEC_USER_AGENT", "")
    monkeypatch.setenv("DP_AUTH_MODE", "demo")
    for k in ("DP_SHOW_RAW_PRICES", "DP_SHOW_TRIGGER_PRICES", "DP_ALLOW_UNOFFICIAL_SOURCES", "DP_PELOSI_PUBLIC"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ALPACA_API_KEY_ID", SENTINEL_KEY)
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", SENTINEL_SECRET)
    _reset()
    from app.auth import DEMO_WORKSPACE_ID
    from app.services.seed import bootstrap_demo
    bootstrap_demo()
    monkeypatch.setenv("DP_AUTH_MODE", "public")
    monkeypatch.setenv("DP_PUBLIC_WORKSPACE_ID", str(DEMO_WORKSPACE_ID))
    monkeypatch.setenv("DP_RATE_LIMIT_PER_MIN", "10000")
    monkeypatch.setenv("DP_RATE_LIMIT_JOBS_PER_MIN", "1000")
    monkeypatch.setenv("DP_RATE_LIMIT_WRITES_PER_MIN", "1000")
    _reset()
    from app.services.public_lab import setup_public_lab
    setup_public_lab(DEMO_WORKSPACE_ID)
    from app.main import create_app
    with TestClient(create_app(), client=("198.51.100.20", 1)) as c:
        yield c
    _reset()


def _fixture_snapshot(c: TestClient, headers: dict | None = None) -> str:
    snaps = c.get("/api/snapshots?symbol=TSLA&interval=5m", headers=headers or {}).json()
    fx = [s for s in snaps if s["is_fixture"]]
    if fx:
        return fx[0]["id"]
    return c.post("/api/snapshots/fixture", headers=headers or {}).json()["id"]


# ---------------------------------------------------------------- defaults per mode

def test_demo_shows_everything(client: TestClient, offline_yahoo: None) -> None:
    pol = client.get("/api/workspace", headers=DEMO).json()["display_policy"]
    assert pol["show_raw_prices"] and pol["allow_unofficial_sources"] and pol["show_trigger_prices"]
    assert pol["pelosi_public"] is False
    r = client.get("/api/assets/TSLA/chart?range=1d", headers=DEMO)
    assert r.status_code == 200 and r.json()["bars"]
    prov = r.json()["provenance"]
    assert prov["provider"] == "yahoo" and prov["official"] is False and prov["terms_url"]


def test_public_defaults_are_restrictive(public_default: TestClient) -> None:
    c = public_default
    pol = c.get("/api/workspace").json()["display_policy"]
    assert pol == {**pol, "show_raw_prices": False, "show_trigger_prices": False, "pelosi_public": False,
                   "allow_unofficial_sources": False, "shared": True}
    assert pol["note"]


def test_public_hides_raw_prices(public_default: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    c = public_default
    r = c.get("/api/assets/TSLA/chart?range=1d")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "display_policy"
    sid = _fixture_snapshot(c)
    r = c.get(f"/api/snapshots/{sid}/bars?date=2026-10-19")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "display_policy"
    # Session list (dates and bar counts, no prices) stays available for the replay picker.
    assert c.get(f"/api/snapshots/{sid}/sessions").status_code == 200


def test_public_quotes_keep_metrics_and_drop_prices(public_default: TestClient,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DP_ALLOW_UNOFFICIAL_SOURCES", "true")  # data in, prices still hidden
    _reset_settings()
    from app.services import market_data as md

    def fake(symbol: str, rng: str, interval: str, use_cache: bool = True):  # noqa: ANN202
        closes = [100 + i for i in range(22)]
        import json
        ts = [1_790_000_000 + 86400 * i for i in range(22)]
        q = {"open": closes, "high": closes, "low": closes, "close": closes, "volume": [1000] * 22}
        return json.dumps({"chart": {"result": [{"meta": {"regularMarketPrice": 121, "shortName": "X"},
                                                 "timestamp": ts, "indicators": {"quote": [q]}}]}}), md.now(), False

    monkeypatch.setattr(md, "fetch_chart_raw", fake)
    body = public_default.get("/api/quotes?symbols=TSLA").json()
    assert body["prices_hidden"] is True
    q = body["quotes"][0]
    assert q["last"] is None and q["volume"] is None and q["avg_volume"] is None and q["spark"] == []
    assert q["change_pct"] is not None and q["volatility_pct"] is not None and q["prices_hidden"] is True


def test_public_refuses_unofficial_source(public_default: TestClient) -> None:
    c = public_default
    r = c.post("/api/timemachine", json=PLAN)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "source_disabled"
    r = c.post("/api/scans", json={"source": "symbols", "symbols": ["TSLA"]})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "source_disabled"
    r = c.get("/api/assets/TSLA/news")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "source_disabled"
    # A stored snapshot is still usable: the server's own simulation on frozen data.
    sid = _fixture_snapshot(c)
    r = c.post("/api/timemachine", json={**PLAN, "snapshot_id": sid}).json()
    j = wait_job(c, r["job"]["id"], headers={})
    assert j["status"] == "succeeded", j.get("error")
    e = c.get(f"/api/experiments/{r['experiment_id']}").json()
    prov = e["results"]["snapshot"]["provenance"]
    assert prov["provider"] == "yahoo" and prov["is_fixture"] is True and prov["official"] is False


def test_scan_results_are_redacted_when_prices_are_hidden(public_default: TestClient) -> None:
    import datetime as dt

    from app.db import scan_runs, tx
    c = public_default
    ws = uuid.UUID(c.get("/api/me").json()["workspace"]["id"])
    sid = uuid.uuid4()
    result = {"hits": [{"symbol": "AMZN", "setups": ["reclaim_ma20"], "price": 260.79, "rsi": 55.9,
                        "volume": 15095309, "close_date": "2026-10-19"}]}
    with tx(None, None) as conn:
        conn.execute(scan_runs.insert().values(id=sid, workspace_id=ws, mode="daily", params={}, status="succeeded",
                                               result=result, created_at=dt.datetime.now(dt.UTC)))
    hit = c.get(f"/api/scans/{sid}").json()["result"]["hits"][0]
    assert hit["price"] is None and hit["volume"] is None
    assert hit["rsi"] == 55.9 and hit["setups"] == ["reclaim_ma20"]


def test_explicit_switches_override_the_mode(public_default: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DP_SHOW_RAW_PRICES", "true")
    _reset_settings()
    assert public_default.get("/api/workspace").json()["display_policy"]["show_raw_prices"] is True


def _reset_settings() -> None:
    from app import config
    config.get_settings.cache_clear()


# ---------------------------------------------------------------- provider status, no secrets

def test_provider_status_never_contains_keys(public_default: TestClient) -> None:
    c = public_default
    body = "".join(c.get(p).text for p in ("/api/workspace", "/api/health", "/api/me", "/api/config",
                                            "/api/market/calendar"))
    assert SENTINEL_KEY not in body and SENTINEL_SECRET not in body
    src = {d["id"]: d for d in c.get("/api/workspace").json()["data_sources"]}
    assert src["yahoo"]["status_code"] == "source_disabled"
    assert src["alpaca"]["status_code"] == "not_integrated"  # key present, adapter in Bloco 3
    assert src["sec_edgar"]["status_code"] == "needs_config"
    assert src["exchange_calendars"]["status_code"] == "active"
    assert all({"name", "use", "status", "tone", "last_fetch", "usage"} <= set(d) for d in src.values())


def test_alpaca_without_key_says_so(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_API_KEY_ID", "")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "")
    _reset_settings()
    src = {d["id"]: d for d in client.get("/api/workspace", headers=DEMO).json()["data_sources"]}
    assert src["alpaca"]["status_code"] == "missing_key"


# ---------------------------------------------------------------- quota, circuit breaker, single flight

def test_per_minute_and_daily_budget(settings_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import providers as p
    monkeypatch.setitem(p.PROVIDERS, "yahoo", p.PROVIDERS["yahoo"].__class__(
        **{**p.PROVIDERS["yahoo"].__dict__, "per_minute": 3, "per_day": 5}))
    for _ in range(3):
        p.acquire("yahoo")
    with pytest.raises(p.ProviderUnavailable) as e:
        p.acquire("yahoo")
    assert e.value.code == "rate_limited" and e.value.retry_after
    g = p._gate("yahoo")
    g.minute.clear()  # a minute later
    p.acquire("yahoo", 2)
    with pytest.raises(p.ProviderUnavailable) as e:
        p.acquire("yahoo")
    assert e.value.code == "quota_exhausted"


def test_circuit_breaker_pauses_after_failures(settings_env: Path) -> None:
    from app.services import providers as p
    for _ in range(p.FAILURES_TO_PAUSE - 1):
        p.failure("sec_edgar")
    p.acquire("sec_edgar")  # still allowed
    p.failure("sec_edgar")
    with pytest.raises(p.ProviderUnavailable) as e:
        p.acquire("sec_edgar")
    assert e.value.code == "provider_paused"
    p._gate("sec_edgar").paused_until = 0
    p.acquire("sec_edgar")
    p.failure("yahoo", "rate_limited")  # a 429 pauses at once
    with pytest.raises(p.ProviderUnavailable):
        p.acquire("yahoo")


def test_single_flight_downloads_once(settings_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from app.services import market_data as md
    calls = []

    class R:
        status_code = 200
        text = '{"chart": {"result": [{"meta": {}, "timestamp": [], "indicators": {"quote": [{}]}}]}}'

    def slow_get(*a, **k):  # noqa: ANN002, ANN003, ANN202
        calls.append(1)
        time.sleep(0.3)
        return R()

    monkeypatch.setattr(httpx, "get", slow_get)
    out = []
    ts = [threading.Thread(target=lambda: out.append(md.fetch_chart_raw("TSLA", "1mo", "1d", use_cache=False)))
          for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(calls) == 1 and len(out) == 4


def test_yahoo_429_pauses_the_provider(settings_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from app.services import market_data as md

    class R:
        status_code = 429
        text = ""

    monkeypatch.setattr(httpx, "get", lambda *a, **k: R())
    monkeypatch.setattr(md.time, "sleep", lambda s: None)
    with pytest.raises(md.DataError) as e:
        md.fetch_chart_raw("TSLA", "1mo", "1d", use_cache=False)
    assert e.value.code == "rate_limited"
    with pytest.raises(md.DataError) as e:
        md.fetch_chart_raw("AAPL", "1mo", "1d", use_cache=False)
    assert e.value.code == "provider_paused"


def test_blank_policy_values_use_the_mode_default(settings_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The lines in .env.example are blank: copying it must not break the settings."""
    for k in ("DP_SHOW_RAW_PRICES", "DP_SHOW_TRIGGER_PRICES", "DP_PELOSI_PUBLIC", "DP_ALLOW_UNOFFICIAL_SOURCES"):
        monkeypatch.setenv(k, "")
    _reset_settings()
    from app.config import get_settings
    s = get_settings()
    assert s.show_raw_prices and s.allow_unofficial_sources and s.dp_pelosi_public is False  # demo mode
