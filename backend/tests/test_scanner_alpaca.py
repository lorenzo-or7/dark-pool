"""Bloco 6: the scanner (daily and ORB) on Alpaca bars downloaded by the server, many symbols per
request, read by trader-scanner unchanged through its offline bundle.

Everything runs on the DERIVED fixtures of tests/scanner_fixtures.py (the skill's own Yahoo files in
Alpaca's format) and a fake HTTP layer; the oracle is the engine reading the ORIGINAL files.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from . import scanner_fixtures as sf
from .conftest import DEMO, _reset, wait_job
from .test_policy import public_default  # noqa: F401  (fixture)

KEY, SECRET = "PKSCANSENTINEL000000000", "SCANSECRETSENTINELneverShow000000000000"


def _daily_ref() -> list[dict]:
    """The engine on the ORIGINAL spark file, 2026-10-19 09:00 ET, no price / volume floor."""
    sc = sf._scanner()
    data, _ = sc.load_offline(str(sf.DAILY))
    return sc.scan_daily(data, sorted(data), sc.parse_now("2026-10-19 09:00"), 0, 0)[0]


def _utc(day: str, hhmm: str) -> dt.datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return dt.datetime.combine(dt.date.fromisoformat(day), dt.time(h, m), sf.NY).astimezone(dt.UTC)


@pytest.fixture()
def api(settings_env: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, sf.FakeAlpacaMulti]]:
    monkeypatch.setenv("ALPACA_API_KEY_ID", KEY)
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", SECRET)
    _reset()
    from app.main import create_app
    from app.services import alpaca
    fake = sf.FakeAlpacaMulti({**sf.daily_bars(), **{}})
    monkeypatch.setattr(alpaca, "_http_get", fake)
    monkeypatch.setattr(alpaca, "_now", lambda: _utc("2026-10-19", "09:00"))
    with TestClient(create_app()) as c:
        yield c, fake


def _scan(c: TestClient, body: dict, headers: dict | None = DEMO) -> dict:
    h = DEMO if headers is None else headers
    r = c.post("/api/scans", json=body, headers=h)
    assert r.status_code == 202, r.text
    j = wait_job(c, r.json()["job"]["id"], headers=h)
    out = c.get(f"/api/scans/{r.json()['scan_id']}", headers=h).json()
    out["_job"] = j
    return out


# ---------------------------------------------------------------- daily

def test_daily_scan_on_alpaca_matches_the_engine_on_the_original_file(api: tuple[TestClient, sf.FakeAlpacaMulti]) -> None:
    c, fake = api
    sc = sf._scanner()
    data, _ = sc.load_offline(str(sf.DAILY))
    syms = sorted(data)
    ref_hits, _, _ = sc.scan_daily(data, syms, sc.parse_now("2026-10-19 09:00"), 0, 0)
    out = _scan(c, {"mode": "daily", "source": "symbols", "symbols": syms, "min_price": 0, "min_volume": 0})
    assert out["_job"]["status"] == "succeeded", out["_job"].get("error")
    res = out["result"]
    assert {h["symbol"]: h["setups"] for h in res["hits"]} == {h["symbol"]: h["setups"] for h in ref_hits}
    assert len(res["hits"]) == len(_daily_ref()) > 10
    assert [h["price"] for h in res["hits"]] == [h["price"] for h in ref_hits]
    assert res["as_of"] == "2026-10-16 close" and res["source"].startswith("Alpaca") and res["mode"] == "daily"
    assert res["data"]["provider"] == "alpaca" and res["data"]["feed"] == "sip"
    # 19 symbols: one request series, one page; every call asks SIP daily bars ending 16 minutes ago
    assert len(fake.calls) == res["data"]["requests"] == 1
    q = fake.calls[0]
    assert (q["timeframe"], q["feed"], q["adjustment"]) == ("1Day", "sip", "all")
    assert q["end"] == "2026-10-19T12:40:00Z" and q["symbols"] == ",".join(syms)   # now - 16 min, 5-min grid
    assert KEY not in json.dumps(out) and SECRET not in json.dumps(out)


def test_daily_scan_pages_and_chunks(api: tuple[TestClient, sf.FakeAlpacaMulti], monkeypatch: pytest.MonkeyPatch) -> None:
    c, fake = api
    from app.services import alpaca
    monkeypatch.setattr(alpaca, "SCAN_CHUNK", 7)
    fake.page_size = 300
    syms = sorted(sf.daily_bars())
    out = _scan(c, {"mode": "daily", "source": "symbols", "symbols": syms, "min_price": 0, "min_volume": 0})
    assert out["_job"]["status"] == "succeeded", out["_job"].get("error")
    assert [h["symbol"] for h in out["result"]["hits"]] == [h["symbol"] for h in _daily_ref()]
    assert len({x["symbols"] for x in fake.calls}) == 3                    # 19 symbols in chunks of 7
    assert len(fake.calls) > 3 and out["result"]["data"]["requests"] == len(fake.calls)


def test_daily_liquidity_filter_reads_the_consolidated_volume(api: tuple[TestClient, sf.FakeAlpacaMulti]) -> None:
    c, _ = api
    syms = sorted(sf.daily_bars())
    out = _scan(c, {"mode": "daily", "source": "symbols", "symbols": syms, "min_price": 5, "min_volume": 1_000_000})
    res = out["result"]
    vols = {s: rows[-1]["v"] for s, rows in sf.daily_bars().items()}
    for h in res["hits"]:
        assert vols[h["symbol"]] >= 1_000_000 and h["volume"] == vols[h["symbol"]]


# ---------------------------------------------------------------- opening-range breakout

def test_orb_scan_replays_a_day_and_matches_the_engine(api: tuple[TestClient, sf.FakeAlpacaMulti],
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    c, fake = api
    from app.services import alpaca
    fake.bars = sf.wall_bars()
    monkeypatch.setattr(alpaca, "_now", lambda: _utc("2026-10-20", "12:00"))
    sc = sf._scanner()
    data, errors = sc.load_offline(str(sf.WALL))
    syms = sorted(set(data) | set(errors))
    day, cutoff = sc.orb_window(sc.parse_now("2026-10-19 10:15"), None, 15, dt.time(15, 30))
    ref, _, _ = sc.scan_orb(data, syms, day, cutoff, 15, 0, 0)
    assert len(ref) == 42
    out = _scan(c, {"mode": "orb", "source": "symbols", "symbols": syms, "day": "2026-10-19", "at": "10:15",
                    "min_price": 0, "min_volume": 0})
    assert out["_job"]["status"] == "succeeded", out["_job"].get("error")
    res = out["result"]
    assert res["mode"] == "orb" and res["as_of"] == "2026-10-19 10:15 ET" and res["or_minutes"] == 15
    keys = ("symbol", "at", "price", "or_high", "or_low", "bar_index", "pct_over")
    assert [{k: h[k] for k in keys} for h in res["hits"]] == [{k: h[k] for k in keys} for h in ref]
    tsla = next(h for h in res["hits"] if h["symbol"] == "TSLA")
    assert (tsla["price"], tsla["at"], tsla["or_high"]) == (364.18, "10:15 AM", 362.18)
    q = fake.calls[0]
    assert (q["timeframe"], q["start"], q["end"]) == ("5Min", "2026-10-19T13:30:00Z", "2026-10-19T14:14:59Z")
    assert res["data"]["requests"] == len(fake.calls) == 2                 # 234 symbols in chunks of 200


def test_orb_live_cut_never_passes_the_free_plan_delay(api: tuple[TestClient, sf.FakeAlpacaMulti],
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    c, fake = api
    from app.services import alpaca
    fake.bars = sf.wall_bars()
    monkeypatch.setattr(alpaca, "_now", lambda: _utc("2026-10-19", "10:33"))   # data up to 10:17 -> cut 10:15
    monkeypatch.setattr("app.services.tasks.datetime", _FrozenDT)
    out = _scan(c, {"mode": "orb", "source": "symbols", "symbols": ["TSLA", "AMD"], "min_price": 0, "min_volume": 0})
    assert out["_job"]["status"] == "succeeded", out["_job"].get("error")
    assert out["result"]["as_of"] == "2026-10-19 10:15 ET"
    late = _scan(c, {"mode": "orb", "source": "symbols", "symbols": ["TSLA"], "day": "2026-10-19", "at": "10:30",
                     "min_price": 0, "min_volume": 0})
    assert late["_job"]["status"] == "failed" and "15 minutos" in (late["_job"].get("error") or "")


class _FrozenDT(dt.datetime):
    @classmethod
    def now(cls, tz=None):  # noqa: ANN001, ANN206
        return _utc("2026-10-19", "10:33") if tz else _utc("2026-10-19", "10:33").replace(tzinfo=None)


def test_orb_with_yahoo_only_reads_today(settings_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DP_SCAN_PROVIDER", "yahoo")
    _reset()
    from app.main import create_app
    with TestClient(create_app()) as c:
        out = _scan(c, {"mode": "orb", "source": "symbols", "symbols": ["TSLA"], "day": "2026-10-19", "at": "10:15"})
    assert out["_job"]["status"] == "failed" and "só lê o pregão de hoje" in out["_job"]["error"]


def test_scan_requests_are_validated(api: tuple[TestClient, sf.FakeAlpacaMulti]) -> None:
    c, _ = api
    for bad in ({"mode": "daily", "symbols": ["TSLA"], "day": "2026-10-19"},
                {"mode": "orb", "symbols": ["TSLA"], "at": "10:12"},
                {"mode": "orb", "symbols": ["TSLA"], "or_minutes": 7},
                {"mode": "weekly", "symbols": ["TSLA"]}):
        assert c.post("/api/scans", json=bad, headers=DEMO).status_code == 422, bad
    r = c.post("/api/scans", json={"mode": "orb", "symbols": ["TSLA"], "day": "2026-09-07"}, headers=DEMO)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "market_closed"


def test_public_lab_hides_orb_levels(public_default: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from app.services import alpaca
    fake = sf.FakeAlpacaMulti(sf.wall_bars())
    monkeypatch.setattr(alpaca, "_http_get", fake)
    monkeypatch.setattr(alpaca, "_now", lambda: _utc("2026-10-20", "12:00"))
    out = _scan(public_default, {"mode": "orb", "source": "symbols", "symbols": ["TSLA", "AMD", "NVDA"],
                                 "day": "2026-10-19", "at": "10:15", "min_price": 0, "min_volume": 0}, headers={})
    hits = out["result"]["hits"]
    assert hits and all(h["price"] is None and h["or_high"] is None and h["or_low"] is None for h in hits)
    assert all(h["pct_over"] is not None and h["at"] for h in hits)
