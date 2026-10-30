# RASCUNHO DO BLOCO 3 — NÃO TESTADO. Escrito antes da interrupção; serve só de referência.
# Destino previsto: backend/app/services/alpaca.py. Revise contra a documentação da Alpaca antes de usar.

"""Alpaca Market Data, Basic plan (IEX feed): historical bars for the server's own calculations.

Reference: https://docs.alpaca.markets/reference/stockbars (read 2026-10-30).
  GET https://data.alpaca.markets/v2/stocks/bars
  headers APCA-API-KEY-ID / APCA-API-SECRET-KEY
  symbols, timeframe (5Min, 1Day...), start / end (RFC-3339, inclusive), limit (max 10,000 data
  points per page, across all symbols), adjustment (raw, split, dividend, spin-off, all),
  feed (iex, sip, otc, boats), sort, page_token; response {bars: {SYM: [{t,o,h,l,c,v,n,vw}]},
  next_page_token}.
Basic plan (https://docs.alpaca.markets/us/docs/about-market-data-api.md): real-time IEX,
200 historical calls per minute, history since 2016, "latest 15 minutes" restricted.

IEX is one exchange, not the consolidated tape: prices are close to it but volume is a small
share of the market, and quiet stocks have 5-minute slots with no IEX trade (no bar). Those
gaps are measured and reported, never filled.

The bars are turned into the chart document the vendored engines already read (Yahoo's v8
chart layout), so no engine is edited. That document is what gets frozen in a snapshot.
"""

from __future__ import annotations

import datetime as dt
import json
from zoneinfo import ZoneInfo

import httpx

from ..config import get_settings
from . import market_calendar as mcal
from . import providers

PROVIDER_ID = "alpaca"
FEED = "iex"
SOURCE = f"alpaca:{FEED}"
URL = "https://data.alpaca.markets/v2/stocks/bars"
PAGE_LIMIT = 10000
MAX_PAGES = 20
RECENT_GAP = dt.timedelta(minutes=16)  # Basic plan: the latest 15 minutes are restricted
NY = ZoneInfo("America/New_York")
TIMEFRAMES = {"5m": ("5Min", 300), "1d": ("1Day", 86400)}
DEFAULT_SESSIONS = 60
MAX_SESSIONS = 250


class AlpacaError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def configured() -> bool:
    s = get_settings()
    return bool(s.alpaca_api_key_id and s.alpaca_api_secret_key)


def _headers() -> dict[str, str]:
    s = get_settings()
    return {"APCA-API-KEY-ID": s.alpaca_api_key_id, "APCA-API-SECRET-KEY": s.alpaca_api_secret_key,
            "Accept": "application/json"}


def _rfc3339(t: dt.datetime) -> str:
    return t.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _message(r: httpx.Response) -> str:
    """Alpaca's own short error text, if any. Never echoes the request (it carries the keys)."""
    try:
        m = r.json().get("message")
    except Exception:  # noqa: BLE001
        m = None
    return str(m)[:200] if m else ""


def fetch_bars(symbol: str, timeframe: str, start: dt.datetime, end: dt.datetime) -> list[dict]:
    """All bars of one symbol between start and end (inclusive), following next_page_token."""
    try:
        providers.check_allowed(PROVIDER_ID)
    except providers.ProviderUnavailable as e:
        raise AlpacaError(e.code, e.message)
    params = {"symbols": symbol, "timeframe": timeframe, "start": _rfc3339(start), "end": _rfc3339(end),
              "limit": PAGE_LIMIT, "adjustment": "all", "feed": FEED, "sort": "asc"}
    out: list[dict] = []
    token: str | None = None
    for _ in range(MAX_PAGES):
        try:
            providers.acquire(PROVIDER_ID)
        except providers.ProviderUnavailable as e:
            raise AlpacaError(e.code, e.message)
        q = dict(params, **({"page_token": token} if token else {}))
        try:
            r = httpx.get(URL, params=q, headers=_headers(), timeout=30)
        except httpx.TimeoutException:
            providers.failure(PROVIDER_ID)
            raise AlpacaError("provider_timeout", "A Alpaca não respondeu a tempo.")
        except httpx.HTTPError as e:
            providers.failure(PROVIDER_ID)
            raise AlpacaError("provider_unreachable", f"Não foi possível acessar a Alpaca ({type(e).__name__}).")
        if r.status_code == 200:
            providers.success(PROVIDER_ID)
            doc = r.json()
            out.extend((doc.get("bars") or {}).get(symbol) or [])
            token = doc.get("next_page_token")
            if not token:
                return out
            continue
        if r.status_code in (401, 403):
            providers.failure(PROVIDER_ID)
            raise AlpacaError("provider_auth", f"A Alpaca recusou a chave do servidor (HTTP {r.status_code}). "
                                               "Confira ALPACA_API_KEY_ID e ALPACA_API_SECRET_KEY.")
        if r.status_code == 429:
            providers.failure(PROVIDER_ID, "rate_limited")
            raise AlpacaError("rate_limited", "A Alpaca está limitando requisições (HTTP 429). Tente em um minuto.")
        if r.status_code in (400, 422):
            raise AlpacaError("provider_bad_request", f"A Alpaca recusou o pedido: {_message(r) or r.status_code}")
        providers.failure(PROVIDER_ID)
        raise AlpacaError("provider_error", f"A Alpaca respondeu HTTP {r.status_code}.")
    raise AlpacaError("too_many_pages", f"Mais de {MAX_PAGES} páginas de dados: peça um período menor.")


# ---------------------------------------------------------------- windows

def session_window(day: dt.date | None, sessions: int, now_utc: dt.datetime | None = None
                   ) -> tuple[dt.datetime, dt.datetime, list[dt.date]]:
    """The `sessions` NYSE sessions before `day` plus `day` itself (the plan's day; default: the
    latest session). -> (start UTC, end UTC, session dates). The end never goes past now minus
    the Basic plan's 15 restricted minutes."""
    if not 1 <= sessions <= MAX_SESSIONS:
        raise AlpacaError("invalid_window", f"Histórico entre 1 e {MAX_SESSIONS} sessões.")
    now_utc = now_utc or dt.datetime.now(dt.UTC)
    cal = mcal._calendar()
    today = now_utc.astimezone(NY).date()
    last = day or today
    if not cal.is_session(last.isoformat()):
        last = cal.date_to_session(last.isoformat(), direction="previous").date()
    first = cal.session_offset(last.isoformat(), -sessions).date()
    dates = [d.date() for d in cal.sessions_in_range(first.isoformat(), last.isoformat())]
    start = cal.session_open(first.isoformat()).to_pydatetime()
    end = min(cal.session_close(last.isoformat()).to_pydatetime(), now_utc - RECENT_GAP)
    if end <= start:
        raise AlpacaError("invalid_window", "O período pedido ainda não tem dados disponíveis no plano gratuito.")
    return start, end, dates


# ---------------------------------------------------------------- engine format and data quality

def _epoch(t: str) -> int:
    return int(dt.datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp())


def to_chart_document(symbol: str, bars: list[dict], interval: str, fetched_at: dt.datetime,
                      window: dict | None = None) -> str:
    """Alpaca bars -> the Yahoo v8 chart layout the engines read. Deterministic text, so the
    same bars always give the same snapshot hash."""
    rows = sorted(((_epoch(b["t"]), b) for b in bars), key=lambda x: x[0])
    meta = {
        "symbol": symbol.replace(".", "-"),
        "dataGranularity": interval,
        "exchangeTimezoneName": "America/New_York",
        "currency": "USD",
        # The engines treat a bar as complete only up to this time; the data is as of the download.
        "regularMarketTime": int(fetched_at.timestamp()),
        "dataProvider": PROVIDER_ID, "feed": FEED, "adjustment": "all",
        "fetchedAt": _rfc3339(fetched_at),
        **({"window": window} if window else {}),
    }
    doc = {"chart": {"error": None, "result": [{
        "meta": meta,
        "timestamp": [t for t, _ in rows],
        "indicators": {"quote": [{
            "open": [b["o"] for _, b in rows], "high": [b["h"] for _, b in rows],
            "low": [b["l"] for _, b in rows], "close": [b["c"] for _, b in rows],
            "volume": [b["v"] for _, b in rows],
        }]},
    }]}}
    return json.dumps(doc, separators=(",", ":"), sort_keys=True)


def session_quality(text: str, dates: list[dt.date]) -> dict:
    """5-minute bars per session against what a full session has (78, or 42 on an early close)."""
    doc = json.loads(text)
    stamps = doc["chart"]["result"][0].get("timestamp") or []
    per_day: dict[str, int] = {}
    for ts in stamps:
        t = dt.datetime.fromtimestamp(ts, NY)
        mins = t.hour * 60 + t.minute
        if ts % 300 == 0 and 570 <= mins < 960:
            per_day[t.date().isoformat()] = per_day.get(t.date().isoformat(), 0) + 1
    sessions = []
    for d in dates:
        info = mcal.day(d)
        expected = (info.close_ny.hour * 60 + info.close_ny.minute - 570) // 5 if info.close_ny else 0
        sessions.append({"date": d.isoformat(), "bars": per_day.get(d.isoformat(), 0), "expected": expected})
    full = [s for s in sessions if s["bars"] == s["expected"] and s["expected"] == 78]
    missing = sum(max(0, s["expected"] - s["bars"]) for s in sessions)
    return {"feed": FEED, "sessions": len(sessions), "full_sessions": len(full),
            "incomplete_sessions": [s for s in sessions if s["bars"] < s["expected"]],
            "missing_bars": missing, "bars": sum(per_day.values()),
            "note": ("Feed IEX: horários sem negócio na IEX não têm candle. O Time Machine usa só sessões "
                     "completas (78 candles); as incompletas ficam de fora.")}


def fetch_session_chart(symbol: str, day: dt.date | None, sessions: int = DEFAULT_SESSIONS
                        ) -> tuple[str, dt.datetime, dict]:
    """5-minute bars for the plan's day and the sessions before it -> (chart text, fetched_at, quality)."""
    start, end, dates = session_window(day, sessions)
    fetched_at = dt.datetime.now(dt.UTC).replace(microsecond=0)
    bars = providers.single_flight(
        (PROVIDER_ID, symbol, "5m", start.isoformat(), end.isoformat()),
        lambda: fetch_bars(symbol, TIMEFRAMES["5m"][0], start, end))
    if not bars:
        raise AlpacaError("unknown_symbol", f"A Alpaca não tem candles de {symbol} no feed IEX nesse período.")
    window = {"first_session": dates[0].isoformat(), "last_session": dates[-1].isoformat(),
              "sessions_requested": sessions, "start": _rfc3339(start), "end": _rfc3339(end)}
    text = to_chart_document(symbol, bars, "5m", fetched_at, window)
    return text, fetched_at, session_quality(text, dates)
