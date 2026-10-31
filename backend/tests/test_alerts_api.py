"""Bloco 5: trader-alerts checked on demand, with quotes for many symbols per request.

Alpaca is a fake HTTP layer; its snapshot bodies are written for these tests from the shape in
Alpaca's documented v2 example (keyed by symbol) and a {"snapshots": ...} wrapper. The Yahoo path
reads the skill's own saved quote files (tests/fixtures/trader-alerts). Nothing here proves how the
real Alpaca API answers; the smoke script does that with real keys.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from .conftest import DEMO, _reset
from .test_policy import public_default  # noqa: F401  (fixture)

FIX = Path(__file__).resolve().parents[1] / "vendor" / "day_trader_skill" / "tests" / "fixtures" / "trader-alerts"
KEY, SECRET = "PKALERTSENTINEL00000000", "ALERTSECRETSENTINELneverShow00000000000"
NOW = dt.datetime(2026, 10, 19, 19, 56)          # 15:56 New York, regular session
RULES = [
    {"id": "tsla-target", "symbol": "TSLA", "type": "target", "price": 366.0},
    {"id": "tsla-stop", "symbol": "TSLA", "type": "stop", "price": 350.0},
    {"id": "ko-move", "symbol": "KO", "type": "pct_move", "pct": 0.3},
    {"id": "bell", "type": "opening_bell"},
    {"id": "flat", "symbol": "TSLA", "type": "time", "at": "15:55", "label": "flat by close", "before_close": True},
]


def _snap(price: float, prev: float, t: str = "2026-10-19T19:40:00Z") -> dict:
    return {"latestTrade": {"t": t, "p": price, "s": 100},
            "dailyBar": {"t": "2026-10-19T04:00:00Z", "o": prev, "h": max(price, prev), "l": min(price, prev), "c": price, "v": 1},
            "prevDailyBar": {"t": "2026-10-16T04:00:00Z", "o": prev, "h": prev, "l": prev, "c": prev, "v": 1}}


class FakeSnapshots:
    def __init__(self, body: dict, status: int = 200):
        self.body, self.status, self.calls = body, status, []

    def __call__(self, params: dict) -> httpx.Response:
        self.calls.append(dict(params))
        req = httpx.Request("GET", "https://data.alpaca.markets/v2/stocks/snapshots")
        if self.status != 200:
            return httpx.Response(self.status, json=self.body, request=req)
        wanted = params["symbols"].split(",")
        inner = self.body.get("snapshots", self.body)
        out = {k: v for k, v in inner.items() if k in wanted}
        return httpx.Response(200, json={"snapshots": out} if "snapshots" in self.body else out, request=req)


@pytest.fixture()
def clock(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.routers import alerts
    monkeypatch.setattr(alerts, "_now", lambda: NOW)


@pytest.fixture()
def alpaca(settings_env: Path, monkeypatch: pytest.MonkeyPatch, clock: None) -> Iterator[tuple[TestClient, FakeSnapshots]]:
    monkeypatch.setenv("ALPACA_API_KEY_ID", KEY)
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", SECRET)
    _reset()
    from app.main import create_app
    from app.services import alpaca as al
    from app.services import market_data as md
    fake = FakeSnapshots({"TSLA": _snap(366.475, 354.72), "KO": _snap(90.11, 89.79)})
    monkeypatch.setattr(al, "_http_get_snapshots", fake)
    monkeypatch.setattr(md, "fetch_chart_raw", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no Yahoo")))
    with TestClient(create_app()) as c:
        yield c, fake


def _check(c: TestClient, rules: list[dict] = RULES, state: dict | None = None, headers: dict | None = DEMO):
    return c.post("/api/alerts/check", json={"rules": rules, **({"state": state} if state else {})},
                  headers=headers if headers is not None else {})


# ---------------------------------------------------------------- Alpaca: one request for every symbol

def test_alpaca_quotes_all_symbols_in_one_request_and_rings_once(alpaca: tuple[TestClient, FakeSnapshots]) -> None:
    c, fake = alpaca
    r = _check(c)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(fake.calls) == 1
    assert fake.calls[0] == {"symbols": "KO,TSLA", "feed": "delayed_sip"}
    ids = {x["id"] for x in body["rings"]}
    assert ids == {"tsla-target", "ko-move", "bell", "flat"}          # 366.475 >= 366; KO +0.36 %; not the stop
    target = next(x for x in body["rings"] if x["id"] == "tsla-target")
    assert "$366.48" in target["message"] and "$366" in target["message"]
    flat = next(x for x in body["rings"] if x["id"] == "flat")
    assert "trader-broker" not in flat["message"]                       # the lab has no broker
    assert body["quotes"]["TSLA"]["price"] == 366.475 and body["quotes"]["KO"]["change_pct"] == 0.356
    assert body["source"]["provider"] == "alpaca" and body["source"]["feed"] == "delayed_sip"
    assert body["source"]["provenance"]["provider"] == "alpaca"
    assert body["market"]["open"] is True and body["errors"] == []
    # the browser sends the state back: nothing rings twice
    again = _check(c, state=body["state"]).json()
    assert again["rings"] == []
    assert KEY not in r.text and SECRET not in r.text


def test_wrapped_body_iex_feed_and_missing_symbol(alpaca: tuple[TestClient, FakeSnapshots],
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    c, fake = alpaca
    monkeypatch.setenv("DP_ALPACA_QUOTE_FEED", "iex")
    from app import config
    config.get_settings.cache_clear()
    fake.body = {"snapshots": {"TSLA": _snap(349.0, 354.72)}}
    body = _check(c, [{"id": "s", "symbol": "TSLA", "type": "stop", "price": 350},
                      {"id": "z", "symbol": "ZZZZ", "type": "above", "price": 1}]).json()
    assert fake.calls[-1]["feed"] == "iex" and [x["id"] for x in body["rings"]] == ["s"]
    assert body["errors"] == [{"symbol": "ZZZZ", "code": "no_data", "message": "A Alpaca não tem cotação de ZZZZ no feed iex."}]


def test_rules_for_another_day_fetch_nothing(alpaca: tuple[TestClient, FakeSnapshots]) -> None:
    c, fake = alpaca
    body = _check(c, [{"id": "old", "symbol": "TSLA", "type": "stop", "price": 400, "date": "2026-10-16"},
                      {"id": "bell", "type": "opening_bell"}]).json()
    assert fake.calls == [] and [x["id"] for x in body["rings"]] == ["bell"]


@pytest.mark.parametrize(("status", "body", "code", "http"), [
    (403, {"code": 42210000, "message": "subscription does not permit querying recent SIP data"}, "provider_subscription", 502),
    (401, {"message": f"bad key {KEY}"}, "provider_auth", 502),
    (429, {"message": "slow down"}, "rate_limited", 503),
    (500, {"message": "oops"}, "provider_error", 502),
])
def test_alpaca_errors(alpaca: tuple[TestClient, FakeSnapshots], status: int, body: dict, code: str, http: int) -> None:
    c, fake = alpaca
    fake.status, fake.body = status, body
    r = _check(c)
    assert r.status_code == http and r.json()["detail"]["code"] == code
    assert KEY not in r.text and SECRET not in r.text


# ---------------------------------------------------------------- Yahoo (no keys): the engine's own parser

def test_yahoo_path_matches_the_engine_reading_the_same_files(client: TestClient, clock: None,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    from app.engines.runner import load_module
    from app.services import market_data as md
    seen = []

    def fake(symbol, rng, interval, use_cache=True):  # noqa: ANN001, ANN202
        seen.append((symbol, rng, interval))
        p = FIX / f"yahoo-{symbol}.json"
        if not p.exists():
            raise md.DataError("provider_unreachable", "offline test")
        return p.read_text(encoding="utf-8"), dt.datetime.now(dt.UTC), False

    monkeypatch.setattr(md, "fetch_chart_raw", fake)
    rules = RULES[:3] + [{"id": "z", "symbol": "ZZZZ", "type": "above", "price": 1}]
    body = _check(client, rules).json()
    assert sorted(seen) == [("KO", "1d", "5m"), ("TSLA", "1d", "5m"), ("ZZZZ", "1d", "5m")]
    al = load_module("alerts")
    ref_quotes, _ = al.get_quotes(["TSLA", "KO"], "yahoo", str(FIX), pause=0)
    ref_rings, _ = al.evaluate([dict(r) for r in RULES[:3]], ref_quotes, al.market_status(NOW), {}, NOW)
    assert [x["id"] for x in body["rings"]] == [x["id"] for x in ref_rings]
    assert [x["message"] for x in body["rings"]] == [x["message"] for x in ref_rings]
    assert body["source"]["provider"] == "yahoo" and body["errors"][0]["symbol"] == "ZZZZ"


# ---------------------------------------------------------------- validation and policy

def test_rules_are_validated(alpaca: tuple[TestClient, FakeSnapshots]) -> None:
    c, _ = alpaca
    r = _check(c, [{"id": "s", "symbol": "TSLA", "type": "stop"}])
    assert r.status_code == 400 and r.json()["detail"]["code"] == "invalid_rule"
    for bad in ([{"type": "stop", "symbol": "TSLA", "price": 1, "webhook": "http://x"}],
                [{"type": "above", "symbol": "TSLA", "price": -1}],
                [{"type": "time", "at": "25:00"}],
                [{"type": "opening_bell"}] * 51, []):
        assert _check(c, bad).status_code == 422, bad


def test_public_lab_hides_prices_in_alerts(public_default: TestClient, clock: None,  # noqa: F811
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import alpaca as al
    fake = FakeSnapshots({"TSLA": _snap(366.475, 354.72), "KO": _snap(90.11, 89.79)})
    monkeypatch.setattr(al, "_http_get_snapshots", fake)
    r = _check(public_default, headers={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["prices_hidden"] is True and {x["id"] for x in body["rings"]} >= {"tsla-target", "ko-move"}
    assert all("price" not in q for q in body["quotes"].values())
    for price in ("366.48", "366.475", "90.11", "89.79", "354.72"):
        assert price not in r.text, price
    assert "[preço oculto]" in json.dumps(body["rings"], ensure_ascii=False)
