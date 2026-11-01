"""Bloco 7: News from SEC 8-K, GDELT headlines and tone, and the Yahoo RSS only where allowed.

SEC and Yahoo answers come from the skill's own saved files (tests/fixtures/trader-news); the
oracle is trader-news reading those same files offline. The GDELT answers are HAND-WRITTEN in the
shape the DOC 2.0 API is documented to return (articles / timeline); they are not collected data.
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

FIX = Path(__file__).resolve().parents[1] / "vendor" / "day_trader_skill" / "tests" / "fixtures" / "trader-news"
UA = "DARK POOL Test test@example.org"
GDELT_ARTICLES = {"articles": [   # HAND-WRITTEN example in the documented ArtList shape
    {"url": "https://news.example.com/apple-1", "url_mobile": "", "title": "Apple unveils new chips",
     "seendate": "20261014T120000Z", "socialimage": "", "domain": "news.example.com", "language": "English",
     "sourcecountry": "United States"},
    {"url": "javascript:alert(1)", "title": "bad link", "seendate": "20261014T120000Z", "domain": "x"},
    {"url": "https://other.example.org/a", "title": "Suppliers react to Apple outlook", "seendate": "20261013T090000Z",
     "domain": "other.example.org", "language": "English", "sourcecountry": "United Kingdom"},
]}
GDELT_TONE = {"timeline": [{"series": "Average Tone", "data": [{"date": "20261013T000000Z", "value": -1.5},
                                                               {"date": "20261014T000000Z", "value": 0.5}]}]}


class Net:
    """Fake SEC (by URL, from the skill's files) and fake Yahoo / GDELT."""

    def __init__(self, gdelt: object = None):
        self.sec, self.http = [], []
        self.gdelt = gdelt

    def sec_get(self, url: str, ua: str) -> httpx.Response:
        self.sec.append((url, ua))
        req = httpx.Request("GET", url)
        if url.endswith("company_tickers.json"):
            return httpx.Response(200, content=(FIX / "company_tickers.json").read_bytes(), request=req)
        cik = url.split("CIK=")[1].split("&")[0]
        p = FIX / f"sec-8-K-{cik}.xml"
        return httpx.Response(200, content=p.read_bytes(), request=req) if p.exists() else httpx.Response(404, request=req)

    def http_get(self, url: str, params: dict | None = None) -> httpx.Response:
        self.http.append((url, dict(params or {})))
        req = httpx.Request("GET", url)
        if "feeds.finance.yahoo.com" in url:
            p = FIX / f"yahoo-{url.split('s=')[1].split('&')[0]}.xml"
            return httpx.Response(200, content=p.read_bytes(), request=req) if p.exists() else httpx.Response(404, request=req)
        if "gdeltproject" in url:
            if isinstance(self.gdelt, httpx.Response):
                return self.gdelt
            body = GDELT_ARTICLES if params["mode"] == "ArtList" else GDELT_TONE
            return httpx.Response(200, text=json.dumps(body), request=req)
        raise AssertionError(url)


@pytest.fixture()
def net(monkeypatch: pytest.MonkeyPatch) -> Net:
    from app.services import news
    n = Net()
    monkeypatch.setattr(news, "_sec_get", n.sec_get)
    monkeypatch.setattr(news, "_http_get", n.http_get)
    news._tickers.update(at=0.0, raw=None, map={})
    news._gdelt_cache.clear()
    return n


@pytest.fixture()
def api(settings_env: Path, monkeypatch: pytest.MonkeyPatch, net: Net) -> Iterator[TestClient]:
    monkeypatch.setenv("SEC_USER_AGENT", UA)
    _reset()
    from app.main import create_app
    with TestClient(create_app()) as c:
        yield c


def _engine_ids(sym: str) -> set[str]:
    """trader-news on the same saved files, offline: the SEC and Yahoo items it finds."""
    from app.engines.runner import load_module
    nw = load_module("news")
    items = nw.collect(nw.Fetcher(offline=str(FIX)), {sym: None}, {}, sec=True, forms=("8-K",), count=10)
    return {it["id"] for it in items}


def test_demo_news_merges_sec_yahoo_and_gdelt(api: TestClient, net: Net) -> None:
    r = api.get("/api/assets/AAPL/news?hours=2160", headers=DEMO)
    assert r.status_code == 200, r.text
    b = r.json()
    ids = {it["id"] for it in b["items"]}
    engine = _engine_ids("AAPL")
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(hours=2160)
    assert {i for i in ids if not i.startswith("gdelt:")} <= engine
    assert any(i.startswith("sec:") for i in ids) and any(i.startswith("rss:") for i in ids)
    assert {"gdelt:https://news.example.com/apple-1", "gdelt:https://other.example.org/a"} <= ids
    assert not any("javascript:" in i for i in ids)                         # unsafe links are dropped
    g = next(it for it in b["items"] if it["id"] == "gdelt:https://news.example.com/apple-1")
    assert (g["source"], g["link"], g["provider"], g["time"]) == ("news.example.com", "https://news.example.com/apple-1",
                                                                   "gdelt", "2026-10-14T12:00:00+00:00")
    assert b["company"] == "Apple Inc." and b["attribution"].startswith("Manchetes e tom: GDELT")
    assert b["coverage_tone"]["average"] == -0.5 and b["coverage_tone"]["points"] == 2
    assert b["sources"] == ["SEC EDGAR (8-K)", "Yahoo Finance RSS", "GDELT"] and b["errors"] == []
    times = [it["time"] for it in b["items"] if it["time"]]
    assert times == sorted(times, reverse=True) and all(t >= cutoff.isoformat()[:10] for t in times[:1])
    # the SEC gets the configured User-Agent; GDELT is queried by the company's name, English sources
    assert all(ua == UA for _, ua in net.sec)
    gq = [p for u, p in net.http if "gdeltproject" in u]
    assert gq[0] == {"query": '"Apple" sourcelang:english', "mode": "ArtList", "format": "json", "maxrecords": "25",
                     "timespan": "7d", "sort": "DateDesc"}
    assert gq[1]["mode"] == "TimelineTone"


def test_sec_ticker_list_is_downloaded_once_and_gdelt_is_cached(api: TestClient, net: Net) -> None:
    api.get("/api/assets/AAPL/news?hours=2160", headers=DEMO)
    api.get("/api/assets/AAPL/news?hours=2160", headers=DEMO)
    assert sum(1 for u, _ in net.sec if u.endswith("company_tickers.json")) == 1
    assert sum(1 for u, _ in net.http if "gdeltproject" in u) == 2           # ArtList + TimelineTone, then cache


def test_gdelt_refusal_keeps_the_rest(api: TestClient, net: Net) -> None:
    net.gdelt = httpx.Response(200, text="Please limit requests to one every 5 seconds.",
                               request=httpx.Request("GET", "https://api.gdeltproject.org/api/v2/doc/doc"))
    b = api.get("/api/assets/AAPL/news?hours=2160", headers=DEMO).json()
    assert any(e.startswith("GDELT:") and "limit" in e for e in b["errors"])
    assert any(it["id"].startswith("sec:") for it in b["items"]) and b["coverage_tone"] is None
    assert "GDELT" not in b["sources"] and b["attribution"] is None


def test_without_user_agent_no_sec_and_no_gdelt(settings_env: Path, net: Net) -> None:
    from app.main import create_app
    with TestClient(create_app()) as c:
        b = c.get("/api/assets/AAPL/news?hours=2160", headers=DEMO).json()
    assert net.sec == [] and not any("gdeltproject" in u for u, _ in net.http)
    assert b["sec_included"] is False and "SEC_USER_AGENT" in b["note"]
    assert {it["id"][:4] for it in b["items"]} == {"rss:"}                   # demo: Yahoo RSS still allowed


def test_public_lab_turns_the_yahoo_rss_off(public_default: TestClient, net: Net,  # noqa: F811
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEC_USER_AGENT", UA)
    from app import config
    config.get_settings.cache_clear()
    b = public_default.get("/api/assets/AAPL/news?hours=2160").json()
    assert not any("feeds.finance.yahoo.com" in u for u, _ in net.http)      # never called
    assert b["yahoo_included"] is False and not any(it["id"].startswith("rss:") for it in b["items"])
    assert any(it["id"].startswith("sec:") for it in b["items"]) and "GDELT" in b["sources"]
    assert "Yahoo" in b["note"] and b["errors"] == []


def test_unknown_ticker_and_name_cleanup(api: TestClient, net: Net) -> None:
    b = api.get("/api/assets/ZZZZ/news?hours=2160", headers=DEMO).json()
    assert b["company"] is None and any("ZZZZ não está na lista" in n for n in b["notes"])
    from app.services.news import query_name
    assert query_name("Apple Inc.") == "Apple" and query_name("Tesla, Inc.") == "Tesla"
    assert query_name("COCA COLA CO") == "COCA COLA" and query_name("BERKSHIRE HATHAWAY INC") == "BERKSHIRE HATHAWAY"
    assert api.get("/api/assets/AAPL/news?hours=0", headers=DEMO).status_code == 422
