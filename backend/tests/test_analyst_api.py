"""Bloco 9: trader-analyst through the server's fetcher, and the earnings 8-K history.

All SEC answers are the skill's own saved files (tests/fixtures/trader-analyst). The oracle is the
engine's own command line reading those files offline (`facts.py AAPL --json --offline DIR`).
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from .conftest import DEMO, _reset

FIX = Path(__file__).resolve().parents[1] / "vendor" / "day_trader_skill" / "tests" / "fixtures" / "trader-analyst"
UA = "DARK POOL Test test@example.org"


class Sec:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, url: str, ua: str) -> httpx.Response:
        assert ua == UA
        self.calls.append(url)
        req = httpx.Request("GET", url)
        if url.endswith("company_tickers.json"):
            p = FIX / "company_tickers.json"
        elif "/companyfacts/" in url or "/submissions/" in url:
            kind = "companyfacts" if "/companyfacts/" in url else "submissions"
            p = FIX / f"{kind}-{url.rsplit('/', 1)[1]}"
        elif url.endswith("/index.json"):
            p = FIX / url.split("/")[-2] / "index.json"
        else:
            p = FIX / "missing"
        return httpx.Response(200, content=p.read_bytes(), request=req) if p.exists() else httpx.Response(404, request=req)


@pytest.fixture()
def api(settings_env: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, Sec]]:
    monkeypatch.setenv("SEC_USER_AGENT", UA)
    _reset()
    from app.main import create_app
    from app.services import news
    sec = Sec()
    monkeypatch.setattr(news, "_sec_get", sec)
    news._tickers.update(at=0.0, raw=None, map={})
    with TestClient(create_app()) as c:
        yield c, sec


def _engine(sym: str) -> dict:
    from app.engines.runner import run_script
    with tempfile.TemporaryDirectory() as d:
        r = run_script("analyst", [sym, "--json", "--offline", str(FIX)], Path(d), timeout_s=60)
    return json.loads(r.stdout)[0]


@pytest.mark.parametrize("sym", ["AAPL", "KO"])
def test_same_numbers_as_the_engine_offline(api: tuple[TestClient, Sec], sym: str) -> None:
    c, _ = api
    r = c.get(f"/api/assets/{sym}/fundamentals", headers=DEMO)
    assert r.status_code == 200, r.text
    b = r.json()
    ref = _engine(sym)
    for k in ("result", "filings", "changes", "note"):
        assert b[k] == ref[k], k
    assert b["ticker"] == sym and b["source"].startswith("SEC EDGAR")


def test_earnings_history_is_history_only(api: tuple[TestClient, Sec]) -> None:
    c, _ = api
    b = c.get("/api/assets/AAPL/fundamentals", headers=DEMO).json()
    sub = json.loads((FIX / "submissions-CIK0000320193.json").read_text())["filings"]["recent"]
    want = [sub["filingDate"][i] for i, f in enumerate(sub["form"]) if f == "8-K" and "2.02" in (sub["items"][i] or "")]
    assert [h["filed"] for h in b["earnings_history"]] == want and want
    h = b["earnings_history"][0]
    assert h["url"].startswith("https://www.sec.gov/Archives/edgar/data/320193/") and "2.02" in h["items"]
    assert "não estima" in b["earnings_history_note"]
    assert not any(k in json.dumps(b).lower() for k in ("next_earnings", "expected_date", "estimated"))


def test_sec_answers_are_cached(api: tuple[TestClient, Sec]) -> None:
    c, sec = api
    first = c.get("/api/assets/AAPL/fundamentals", headers=DEMO).json()
    n = len(sec.calls)
    assert first["sec"]["requests"] >= 3                                  # facts, submissions, index.json
    again = c.get("/api/assets/AAPL/fundamentals", headers=DEMO).json()
    assert len(sec.calls) == n and again["sec"] == {"requests": 0, "from_cache": first["sec"]["requests"]}
    assert again["result"] == first["result"]


def test_errors(api: tuple[TestClient, Sec], monkeypatch: pytest.MonkeyPatch) -> None:
    c, _ = api
    r = c.get("/api/assets/ZZZZ/fundamentals", headers=DEMO)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "unknown_symbol"
    r = c.get("/api/assets/BAC/fundamentals", headers=DEMO)              # in the list, no companyfacts file -> SEC 404
    assert r.status_code == 422 and r.json()["detail"]["code"] == "no_xbrl"
    assert c.get("/api/assets/AAPL/fundamentals?quarters=40", headers=DEMO).status_code == 422
    monkeypatch.setenv("SEC_USER_AGENT", "")
    from app import config
    config.get_settings.cache_clear()
    r = c.get("/api/assets/AAPL/fundamentals", headers=DEMO)
    assert r.status_code == 424 and r.json()["detail"]["code"] == "sec_user_agent_missing"
