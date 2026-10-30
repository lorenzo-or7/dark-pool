"""DERIVED test fixture in Alpaca's response format. NOT collected from Alpaca.

Built at test time from the day-trader-skill's saved Yahoo file
(vendor/day_trader_skill/tests/fixtures/trader-timemachine/TSLA-60d5m.json.gz, fetched by the
skill's author on 2026-10-19 10:49:45 ET). Every regular-session 5-minute bar that had ENDED by
that time becomes one Alpaca bar {t, o, h, l, c, v} with the same prices and volume; t is the
bar's start in RFC-3339 UTC. The partial 10:45 bar and Yahoo's live tick are left out, since the
source data for them was not complete. n and vw do not exist in the source and are null.

`FakeAlpaca` answers like GET /v2/stocks/bars: start and end inclusive, ascending, and pages of
at most `page_size` bars with next_page_token (the documented "the API may return less").
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
from pathlib import Path

import httpx

NY = dt.timezone(dt.timedelta(hours=-4))  # all fixture sessions are in EDT
SKILL_FILE = (Path(__file__).resolve().parent.parent / "vendor" / "day_trader_skill" / "tests" / "fixtures"
              / "trader-timemachine" / "TSLA-60d5m.json.gz")
DERIVED_NOTE = "derived from the skill's TSLA-60d5m.json.gz (Yahoo), not collected from Alpaca"
YAHOO_AS_OF = 1792421385  # meta.regularMarketTime of the skill's file (2026-10-19 10:49:45 ET)


def rfc3339(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts, dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def yahoo_text() -> str:
    with gzip.open(SKILL_FILE, "rt", encoding="utf-8") as fh:
        return fh.read()


def derived_bars() -> list[dict]:
    r0 = json.loads(yahoo_text())["chart"]["result"][0]
    q = r0["indicators"]["quote"][0]
    out = []
    for i, ts in enumerate(r0["timestamp"]):
        o, h, lo, c, v = (q[k][i] for k in ("open", "high", "low", "close", "volume"))
        if ts is None or None in (o, h, lo, c) or ts % 300 or ts + 300 > YAHOO_AS_OF:
            continue
        local = dt.datetime.fromtimestamp(ts, NY)
        mins = local.hour * 60 + local.minute
        if not 570 <= mins < 960:
            continue
        out.append({"t": rfc3339(ts), "o": o, "h": h, "l": lo, "c": c, "v": int(v or 0), "n": None, "vw": None})
    return out


class FakeAlpaca:
    """Stand-in for alpaca._http_get. Records the calls (params only; headers are checked apart)."""

    def __init__(self, bars: list[dict], symbol: str = "TSLA", page_size: int = 1000,
                 status: int = 200, body: dict | None = None, exc: Exception | None = None):
        self.bars = sorted(bars, key=lambda b: b["t"])
        self.symbol = symbol
        self.page_size = page_size
        self.status = status
        self.body = body
        self.exc = exc
        self.calls: list[dict] = []

    def __call__(self, params: dict) -> httpx.Response:
        self.calls.append(dict(params))
        req = httpx.Request("GET", "https://data.alpaca.markets/v2/stocks/bars")
        if self.exc is not None:
            raise self.exc
        if self.status != 200:
            return httpx.Response(self.status, json=self.body or {"message": "error"}, request=req)
        start, end = params["start"], params["end"]
        sel = [b for b in self.bars if start <= b["t"] <= end] if params["symbols"] == self.symbol else []
        offset = int(params.get("page_token") or 0)
        page = sel[offset: offset + min(self.page_size, int(params["limit"]))]
        nxt = offset + len(page)
        doc = {"bars": {self.symbol: page} if page else {},
               "next_page_token": str(nxt) if nxt < len(sel) else None, "_fixture": DERIVED_NOTE}
        return httpx.Response(200, json=doc, request=req)


def edt(day: str, hhmm: str) -> dt.datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return dt.datetime.combine(dt.date.fromisoformat(day), dt.time(h, m), NY).astimezone(dt.UTC)
