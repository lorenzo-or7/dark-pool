"""DERIVED Alpaca fixtures for the scanner (Bloco 6): the skill's own saved Yahoo files rewritten in
Alpaca's bars format. NOT data collected from Alpaca.

- daily: tests/fixtures/trader-scanner/daily-spark-2026-10-19.json (19 daily charts, closes only):
  o = h = l = c; each bar at midnight New York (Alpaca's 1Day `t`); volume 0 except the last bar,
  which carries the spark meta's regularMarketVolume (what the daily filter reads).
- 5-minute: wall5m-2026-10-19.json.gz (234 charts of 2026-10-19): every on-grid bar with a close.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

NY = ZoneInfo("America/New_York")
SDIR = Path(__file__).resolve().parents[1] / "vendor" / "day_trader_skill" / "tests" / "fixtures" / "trader-scanner"
DAILY = SDIR / "daily-spark-2026-10-19.json"
WALL = SDIR / "wall5m-2026-10-19.json.gz"
NOTE = "DERIVED fixture: the skill's Yahoo files rewritten in Alpaca's format; not collected from Alpaca."


def _iso(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts, dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _scanner():
    from app.engines.runner import load_module
    return load_module("scanner")


def daily_bars() -> dict[str, list[dict]]:
    data, _ = _scanner().load_offline(str(DAILY))
    out = {}
    for sym, s in data.items():
        rows = []
        days = {}
        for ts, c in zip(s["t"], s["c"]):
            if c is not None:
                days[dt.datetime.fromtimestamp(ts, NY).date()] = float(c)
        for d in sorted(days):
            midnight = dt.datetime.combine(d, dt.time(0, 0), NY)
            c = days[d]
            rows.append({"t": _iso(int(midnight.timestamp())), "o": c, "h": c, "l": c, "c": c, "v": 0})
        if rows:
            rows[-1]["v"] = int((s.get("meta") or {}).get("regularMarketVolume") or 0)
            out[sym] = rows
    return out


def wall_bars() -> dict[str, list[dict]]:
    data, _ = _scanner().load_offline(str(WALL))
    out = {}
    for sym, s in data.items():
        rows = []
        for i, ts in enumerate(s["t"]):
            c = s["c"][i]
            if c is None or ts is None or ts % 300:
                continue
            h, lo, o = (s[k][i] if s.get(k) else None for k in ("h", "l", "o"))
            v = (s.get("v") or [0] * len(s["t"]))[i] or 0
            rows.append({"t": _iso(int(ts)), "o": o if o is not None else c, "h": h if h is not None else c,
                         "l": lo if lo is not None else c, "c": c, "v": int(v)})
        if rows:
            out[sym] = rows
    return out


class FakeAlpacaMulti:
    """Stand-in for alpaca._http_get with many symbols: bars sorted by symbol, then time, `limit`
    counted across symbols, next_page_token = an offset (Alpaca's token is opaque)."""

    def __init__(self, bars: dict[str, list[dict]], page_size: int = 10000):
        self.bars = bars
        self.page_size = page_size
        self.calls: list[dict] = []

    def __call__(self, params: dict) -> httpx.Response:
        self.calls.append(dict(params))
        req = httpx.Request("GET", "https://data.alpaca.markets/v2/stocks/bars")
        flat = []
        for sym in sorted(params["symbols"].split(",")):
            for b in self.bars.get(sym, []):
                if params["start"] <= b["t"] <= params["end"]:
                    flat.append((sym, b))
        off = int(params.get("page_token") or 0)
        page = flat[off: off + min(self.page_size, int(params["limit"]))]
        doc: dict = {"bars": {}, "_fixture": NOTE}
        for sym, b in page:
            doc["bars"].setdefault(sym, []).append(b)
        doc["next_page_token"] = str(off + len(page)) if off + len(page) < len(flat) else None
        return httpx.Response(200, json=doc, request=req)


def wall_text() -> str:
    with gzip.open(WALL, "rt", encoding="utf-8") as fh:
        return fh.read()


def daily_doc() -> dict:
    return json.loads(DAILY.read_text(encoding="utf-8"))
