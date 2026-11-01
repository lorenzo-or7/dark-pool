"""Bloco 8: SEC metadata (CIK, exchanges, SIC, SIC division as the sector).

company_tickers.json and the submissions file are the skill's own saved SEC files; the submissions
file there is an excerpt, so `sic`, `sicDescription`, `category` and `stateOfIncorporation` are ADDED
BY HAND below (values as the SEC publishes them for Apple), marked as such.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from .conftest import DEMO, _reset

NEWS = Path(__file__).resolve().parents[1] / "vendor" / "day_trader_skill" / "tests" / "fixtures" / "trader-news"
ANALYST = NEWS.parent / "trader-analyst"
UA = "DARK POOL Test test@example.org"
HAND_ADDED = {"sic": "3571", "sicDescription": "Electronic Computers", "category": "Large accelerated filer",
              "stateOfIncorporation": "CA", "entityType": "operating"}


class Sec:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, url: str, ua: str) -> httpx.Response:
        assert ua == UA
        self.calls.append(url)
        req = httpx.Request("GET", url)
        if url.endswith("company_tickers.json"):
            return httpx.Response(200, content=(NEWS / "company_tickers.json").read_bytes(), request=req)
        if url.endswith("CIK0000320193.json"):
            doc = json.loads((ANALYST / "submissions-CIK0000320193.json").read_text(encoding="utf-8"))
            return httpx.Response(200, json={**doc, **HAND_ADDED}, request=req)
        return httpx.Response(404, request=req)


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


def test_profile_from_sec_files(api: tuple[TestClient, Sec], settings_env: Path) -> None:
    c, sec = api
    r = c.get("/api/assets/AAPL/profile", headers=DEMO)
    assert r.status_code == 200, r.text
    p = r.json()
    assert (p["cik"], p["name"], p["exchanges"], p["tickers"]) == ("0000320193", "Apple Inc.", ["Nasdaq"], ["AAPL"])
    assert (p["sic"], p["sic_description"], p["fiscal_year_end"]) == ("3571", "Electronic Computers", "0926")
    assert p["sector"] == {"division": "D", "name": "Indústria de transformação", "sic_range": "20–39"}
    assert p["from_cache"] is False and p["sec_url"].endswith("CIK=0000320193")
    assert not {"market_cap", "float", "shares_float"} & set(p)              # out of scope by decision
    # cached on disk without the filing history; the second call does not reach the SEC
    cached = json.loads((settings_env / "data" / "cache" / "sec_submissions" / "CIK0000320193.json").read_text())
    assert "filings" not in cached and cached["sic"] == "3571"
    n = len(sec.calls)
    again = c.get("/api/assets/AAPL/profile", headers=DEMO).json()
    assert len(sec.calls) == n and again["from_cache"] is True and again["sector"]["division"] == "D"


def test_unknown_symbol_missing_filing_and_no_user_agent(api: tuple[TestClient, Sec], settings_env: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    c, _ = api
    r = c.get("/api/assets/ZZZZ/profile", headers=DEMO)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "unknown_symbol"
    r = c.get("/api/assets/KO/profile", headers=DEMO)                     # no submissions file -> SEC 404
    assert r.status_code == 502 and r.json()["detail"]["code"] == "provider_error"
    monkeypatch.setenv("SEC_USER_AGENT", "")
    from app import config
    config.get_settings.cache_clear()
    r = c.get("/api/assets/AAPL/profile", headers=DEMO)
    assert r.status_code == 424 and r.json()["detail"]["code"] == "sec_user_agent_missing"


@pytest.mark.parametrize(("code", "division"), [
    ("0100", "A"), ("0971", "A"), ("1311", "B"), ("1531", "C"), ("2834", "D"), ("3999", "D"), ("4813", "E"),
    ("5045", "F"), ("5961", "G"), ("6022", "H"), ("6798", "H"), ("7372", "I"), ("8999", "I"), ("9721", "J"),
    ("9995", "K"), ("1800", None), ("6800", None), ("9800", None), ("", None), ("abc", None), (None, None),
])
def test_sic_divisions(code: str | None, division: str | None) -> None:
    from app.services.sec_profile import sic_division
    d = sic_division(code)
    assert (d["division"] if d else None) == division
