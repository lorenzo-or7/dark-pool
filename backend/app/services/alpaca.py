"""Alpaca Market Data, Basic plan: 5-minute bars for the server's own calculations.

Documentation read on 2026-10-30 and 2026-10-31:
  https://docs.alpaca.markets/reference/stockbars (historical bars, several symbols)
  https://docs.alpaca.markets/us/reference/stockbarsingle-1 (same parameters, one symbol)
  https://docs.alpaca.markets/us/docs/about-market-data-api.md (Basic plan)
  https://docs.alpaca.markets/us/docs/market-data-faq (SIP without a subscription)

  GET https://data.alpaca.markets/v2/stocks/bars, headers APCA-API-KEY-ID / APCA-API-SECRET-KEY.
  symbols, timeframe (5Min), start / end (RFC-3339, both inclusive), limit (1 to 10,000 data
  points per page, across all symbols; "the API may return less ... always check the
  next_page_token"), adjustment (raw by default; here all), feed (sip, iex, ...), sort,
  page_token. Response {bars: {SYM: [{t, o, h, l, c, v, n, vw}]}, next_page_token}.
  Basic plan: real-time IEX, history since 2016, 200 historical calls per minute, and the
  latest 15 minutes restricted. Per the FAQ, without a subscription SIP history can be queried
  when `end` is at least 15 minutes old; a newer `end` is refused with a "subscription does not
  permit ..." message (code 42210000).

Feed (DP_ALPACA_FEED): "sip" by default, the consolidated tape of every US exchange, which the
Basic plan serves for anything older than 15 minutes; this module never asks for newer data.
"iex" (one exchange, about 2% of the volume, gaps on quiet stocks) stays available as a setting.

What this module does, and what it refuses to do:

- The window is counted in NYSE sessions (services/market_calendar.py), not calendar days.
- `data_end` is the honest "data complete up to" instant: a 5-minute boundary that is never
  later than the last session's close nor later than now minus 16 minutes. Only bars that START
  before it are requested and kept, so every kept bar has fully ended by `data_end`.
  `meta.regularMarketTime` is set to `data_end`, never to the download time: the engines treat a
  bar as complete only when it ends by that instant, and nothing pretends to be later than it is.
- Bar timestamps are kept exactly as Alpaca sends them (bar start, UTC). Bars outside the regular
  session (pre-market, after-hours) are left out of the document and counted.
- A 5-minute slot with no trade on the feed has no bar (rare on SIP for listed stocks, common on
  IEX). Those gaps are measured (`session_quality`) and reported; they are never filled.
- Errors never repeat the request headers, and any text that would be shown is scrubbed of the
  configured key and secret.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass

import httpx

from ..config import get_settings
from . import market_calendar as mcal
from . import providers

PROVIDER_ID = "alpaca"
FEEDS = ("sip", "iex")
SOURCES = tuple(f"{PROVIDER_ID}:{f}" for f in FEEDS)
ADJUSTMENT = "all"
FEED_LABEL = {"sip": "SIP (consolidado das bolsas dos EUA)", "iex": "IEX (uma única bolsa)"}
URL = "https://data.alpaca.markets/v2/stocks/bars"
TIMEFRAME_5M = "5Min"
BAR_S = 300
PAGE_LIMIT = 10000
MAX_PAGES = 20
# Basic plan: the latest 15 minutes are restricted. One more minute of margin.
RECENT_GAP = dt.timedelta(minutes=16)
DEFAULT_SESSIONS = 60
MIN_SESSIONS = 20      # the Time Machine engine needs at least 20 full sessions
MAX_SESSIONS = 250
FULL_SESSION_BARS = 78
OPEN_MIN = 9 * 60 + 30


class AlpacaError(Exception):
    def __init__(self, code: str, message: str):
        message = scrub(message)
        super().__init__(message)
        self.code = code
        self.message = message


def configured() -> bool:
    s = get_settings()
    return bool(s.alpaca_api_key_id and s.alpaca_api_secret_key)


def feed() -> str:
    """The feed new downloads use (DP_ALPACA_FEED)."""
    return get_settings().dp_alpaca_feed


def source(f: str | None = None) -> str:
    """The snapshot source of a feed: alpaca:sip or alpaca:iex."""
    return f"{PROVIDER_ID}:{f or feed()}"


def is_alpaca_source(src: str | None) -> bool:
    return src in SOURCES


def limitation(src: str | None) -> str:
    """The plain-words caveat of an Alpaca snapshot, by feed."""
    if src == source("iex"):
        return ("Feed IEX (Alpaca, plano gratuito): uma única bolsa, não o consolidado. Volume muito menor que o do "
                "mercado; horários sem negócio na IEX não têm candle e as sessões incompletas ficam de fora.")
    return ("Feed SIP da Alpaca (consolidado das bolsas dos EUA), plano gratuito: só dados com mais de 15 minutos. "
            "Horários sem negócio não têm candle e as sessões incompletas ficam de fora (nada é preenchido).")


def scrub(text: str) -> str:
    """Remove the configured key and secret from any text that could reach a user or a log."""
    s = get_settings()
    for secret in (s.alpaca_api_key_id, s.alpaca_api_secret_key):
        if secret and len(secret) >= 4:
            text = text.replace(secret, "[oculto]")
    return text


def _headers() -> dict[str, str]:
    s = get_settings()
    return {"APCA-API-KEY-ID": s.alpaca_api_key_id, "APCA-API-SECRET-KEY": s.alpaca_api_secret_key,
            "Accept": "application/json"}


def _rfc3339(t: dt.datetime) -> str:
    return t.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _http_get(params: dict) -> httpx.Response:
    """The only network call. Tests replace it."""
    return httpx.get(URL, params=params, headers=_headers(), timeout=30)


def _message(r: httpx.Response) -> str:
    """Alpaca's own short error text, if any (scrubbed by AlpacaError)."""
    try:
        m = r.json().get("message")
    except Exception:  # noqa: BLE001
        m = None
    return str(m)[:200] if m else ""


# ---------------------------------------------------------------- download

def _subscription_refusal(r: httpx.Response) -> bool:
    """Alpaca's 'subscription does not permit ...' answer (code 42210000), whatever the HTTP status."""
    try:
        body = r.json()
    except Exception:  # noqa: BLE001
        return False
    if not isinstance(body, dict):
        return False
    return str(body.get("code")) == "42210000" or "subscription" in str(body.get("message", "")).lower()


def fetch_bars(symbol: str, timeframe: str, start: dt.datetime, end: dt.datetime,
               feed_name: str | None = None) -> list[dict]:
    """Every bar of one symbol between start and end (both inclusive), following next_page_token.
    Each page spends one call of the shared quota; a refusal stops the download (no partial data)."""
    try:
        providers.check_allowed(PROVIDER_ID)
    except providers.ProviderUnavailable as e:
        raise AlpacaError(e.code, e.message)
    f = feed_name or feed()
    params = {"symbols": symbol, "timeframe": timeframe, "start": _rfc3339(start), "end": _rfc3339(end),
              "limit": PAGE_LIMIT, "adjustment": ADJUSTMENT, "feed": f, "sort": "asc"}
    out: list[dict] = []
    token: str | None = None
    for _ in range(MAX_PAGES):
        try:
            providers.acquire(PROVIDER_ID)
        except providers.ProviderUnavailable as e:
            raise AlpacaError(e.code, e.message)
        q = dict(params, **({"page_token": token} if token else {}))
        try:
            r = _http_get(q)
        except httpx.TimeoutException:
            providers.failure(PROVIDER_ID)
            raise AlpacaError("provider_timeout", "A Alpaca não respondeu a tempo.")
        except httpx.HTTPError as e:
            providers.failure(PROVIDER_ID)
            raise AlpacaError("provider_unreachable", f"Não foi possível acessar a Alpaca ({type(e).__name__}).")
        if r.status_code == 200:
            try:
                doc = r.json()
                page = (doc.get("bars") or {}).get(symbol) or []
                token = doc.get("next_page_token")
            except (ValueError, AttributeError):
                providers.failure(PROVIDER_ID)
                raise AlpacaError("bad_payload", "A Alpaca devolveu um formato inesperado.")
            providers.success(PROVIDER_ID)
            out.extend(page)
            if not token:
                return out
            continue
        if r.status_code in (403, 422) and _subscription_refusal(r):
            # Not a key problem and not worth tripping the breaker: the plan does not cover this request.
            raise AlpacaError("provider_subscription",
                              f"O plano da Alpaca não cobre esse pedido no feed {f.upper()} (HTTP {r.status_code}). "
                              "No plano gratuito o SIP só vale para dados com mais de 15 minutos; se persistir, "
                              "use DP_ALPACA_FEED=iex.")
        if r.status_code in (401, 403):
            providers.failure(PROVIDER_ID)
            raise AlpacaError("provider_auth", f"A Alpaca recusou a chave do servidor (HTTP {r.status_code}). "
                                               "Confira ALPACA_API_KEY_ID e ALPACA_API_SECRET_KEY.")
        if r.status_code == 429:
            providers.failure(PROVIDER_ID, "rate_limited")
            raise AlpacaError("rate_limited", "A Alpaca está limitando requisições (HTTP 429). Tente em um minuto.")
        if r.status_code in (400, 422):
            raise AlpacaError("provider_bad_request",
                              f"A Alpaca recusou o pedido (HTTP {r.status_code}): {_message(r) or 'sem detalhe'}")
        providers.failure(PROVIDER_ID)
        raise AlpacaError("provider_error", f"A Alpaca respondeu HTTP {r.status_code}.")
    raise AlpacaError("too_many_pages", f"Mais de {MAX_PAGES} páginas de dados: peça menos sessões.")


# ---------------------------------------------------------------- window (NYSE sessions)

@dataclass(frozen=True)
class Window:
    plan_day: dt.date | None       # the Time Machine's day; None for a backtest
    sessions: tuple[dt.date, ...]  # oldest first; the last one is the plan's day (or the last closed session)
    start: dt.datetime             # UTC, open of the first session
    data_end: dt.datetime          # UTC, on the 5-minute grid; bars starting before it are complete
    sessions_requested: int

    def meta(self) -> dict:
        return {"plan_day": self.plan_day.isoformat() if self.plan_day else None,
                "sessions_requested": self.sessions_requested,
                "sessions": [d.isoformat() for d in self.sessions],
                "start": _rfc3339(self.start), "data_end": _rfc3339(self.data_end)}


def _floor5(t: dt.datetime) -> dt.datetime:
    ts = int(t.timestamp())
    return dt.datetime.fromtimestamp(ts - ts % BAR_S, dt.UTC)


def _open_close(d: dt.date) -> tuple[dt.datetime, dt.datetime]:
    cal = mcal._calendar()
    return (cal.session_open(d.isoformat()).to_pydatetime().astimezone(dt.UTC),
            cal.session_close(d.isoformat()).to_pydatetime().astimezone(dt.UTC))


def _now() -> dt.datetime:
    """The server clock (tests replace it)."""
    return dt.datetime.now(dt.UTC)


def available_until(now_utc: dt.datetime | None = None) -> dt.datetime:
    """The latest instant the Basic plan serves, on the 5-minute grid."""
    return _floor5((now_utc or _now()) - RECENT_GAP)


def session_window(day: dt.date | None, sessions: int, now_utc: dt.datetime | None = None,
                   min_sessions: int = MIN_SESSIONS) -> Window:
    """With a day (Time Machine): `sessions` NYSE sessions before `day`, plus `day` itself
    (sessions=0 with min_sessions=0: only that day, for the ORB plan of Entry and Exit).
    Without (ORB backtest): the last `sessions` sessions that have already closed for the plan.
    The data never goes past now minus 16 minutes (the Basic plan's restricted 15 minutes)."""
    if not min_sessions <= sessions <= MAX_SESSIONS or (day is None and sessions < 1):
        raise AlpacaError("invalid_window", f"Histórico entre {min_sessions} e {MAX_SESSIONS} sessões.")
    limit = available_until(now_utc)
    cal = mcal._calendar()
    all_sessions = [ts.date() for ts in cal.sessions]
    if day is not None:
        if day not in set(all_sessions):
            raise AlpacaError("market_closed", f"A NYSE não abriu em {day.isoformat()}.")
        idx = all_sessions.index(day)
        o, c = _open_close(day)
        if o >= limit:
            raise AlpacaError("not_available_yet",
                              f"Os candles de {day.isoformat()} ainda não estão disponíveis: o plano gratuito da "
                              "Alpaca libera os dados com 15 minutos de atraso.")
        count_before = sessions
    else:
        # The latest session already closed by `limit`.
        idx = max(i for i, d in enumerate(all_sessions) if d <= limit.date())
        while idx >= 0 and _open_close(all_sessions[idx])[1] > limit:
            idx -= 1
        count_before = sessions - 1
    if idx - count_before < 0:
        raise AlpacaError("invalid_window", "O calendário do servidor não cobre tantas sessões para trás.")
    chosen = tuple(all_sessions[idx - count_before: idx + 1])
    start = _open_close(chosen[0])[0]
    data_end = min(_open_close(chosen[-1])[1], limit)
    return Window(day, chosen, start, data_end, sessions)


# ---------------------------------------------------------------- engine format (Yahoo v8 chart layout)

def _epoch(t: str) -> int:
    return int(dt.datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp())


def to_chart_document(symbol: str, bars: list[dict], window: Window, feed_name: str = "sip") -> str:
    """Alpaca bars -> the Yahoo v8 chart layout the engines read, as deterministic JSON text.

    The snapshot hash is the SHA-256 of exactly this text, so it depends on: the bars kept
    (timestamp, o, h, l, c, v), meta.symbol, dataGranularity, exchangeTimezoneName, currency,
    regularMarketTime (= data_end), dataProvider, feed, adjustment, the window (plan day,
    sessions, start, data_end, sessions requested) and the count of bars left out. It does not
    depend on the download time, on the order the bars arrived in, on Alpaca's n / vw fields,
    nor on the quality report (derived from this text) or the provenance (derived from the source).
    """
    by_day = {d: tuple(int(x.timestamp()) for x in _open_close(d)) for d in window.sessions}
    end_ts = int(window.data_end.timestamp())
    kept: dict[int, dict] = {}
    dropped = {"outside_regular_hours": 0, "after_data_end": 0, "duplicate": 0}
    for b in bars:
        ts = _epoch(b["t"])
        d = dt.datetime.fromtimestamp(ts, mcal.NY).date()
        oc = by_day.get(d)
        if oc is None or not oc[0] <= ts < oc[1]:
            dropped["outside_regular_hours"] += 1
            continue
        if ts >= end_ts:
            dropped["after_data_end"] += 1
            continue
        if ts in kept:
            dropped["duplicate"] += 1
            continue
        kept[ts] = b
    stamps = sorted(kept)
    meta = {
        "symbol": symbol.replace(".", "-"),
        "dataGranularity": "5m",
        "exchangeTimezoneName": "America/New_York",
        "currency": "USD",
        "regularMarketTime": end_ts,
        "dataProvider": PROVIDER_ID,
        "feed": feed_name,
        "adjustment": ADJUSTMENT,
        "window": window.meta(),
        "leftOut": dropped,
    }
    doc = {"chart": {"error": None, "result": [{
        "meta": meta,
        "timestamp": stamps,
        "indicators": {"quote": [{
            "open": [kept[t]["o"] for t in stamps], "high": [kept[t]["h"] for t in stamps],
            "low": [kept[t]["l"] for t in stamps], "close": [kept[t]["c"] for t in stamps],
            "volume": [int(kept[t]["v"]) for t in stamps],
        }]},
    }]}}
    return json.dumps(doc, separators=(",", ":"), sort_keys=True, ensure_ascii=True)


# ---------------------------------------------------------------- data quality

def _hhmm(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts, mcal.NY).strftime("%H:%M")


def session_quality(text: str, before: dt.date | None = None) -> dict:
    """Bars per session against what the session has, from the snapshot text alone.

    States: "closed" (the session ended by data_end; fewer bars than expected = IEX gaps),
    "in_progress" (data_end falls inside the session; expected = slots ended by data_end),
    "not_started". `pool_sessions`: closed sessions with all 78 bars before `before`
    (default: the window's plan day; none for a backtest), which is what the engines use."""
    doc = json.loads(text)
    r0 = doc["chart"]["result"][0]
    meta = r0.get("meta") or {}
    w = meta.get("window") or {}
    data_end = _epoch(w["data_end"])
    stamps = r0.get("timestamp") or []
    present: dict[str, set[int]] = {}
    for ts in stamps:
        if ts % BAR_S == 0:
            present.setdefault(dt.datetime.fromtimestamp(ts, mcal.NY).date().isoformat(), set()).add(ts)
    if before is None and w.get("plan_day"):
        before = dt.date.fromisoformat(w["plan_day"])
    sessions = []
    for ds in w.get("sessions") or []:
        d = dt.date.fromisoformat(ds)
        o, c = (int(x.timestamp()) for x in _open_close(d))
        if c <= data_end:
            state, upto = "closed", c
        elif o < data_end:
            state, upto = "in_progress", data_end
        else:
            state, upto = "not_started", o
        slots = list(range(o, upto, BAR_S))
        have = present.get(ds, set())
        missing = [t for t in slots if t not in have]
        sessions.append({"date": ds, "state": state, "bars": sum(1 for t in slots if t in have),
                         "expected": len(slots), "full_length": (c - o) // BAR_S,
                         "early_close": (c - o) // BAR_S < FULL_SESSION_BARS,
                         "missing": len(missing), "missing_times": [_hhmm(t) for t in missing[:12]]})
    closed = [s for s in sessions if s["state"] == "closed"]
    complete = [s for s in closed if s["missing"] == 0]
    incomplete = [s for s in closed if s["missing"] > 0]
    in_progress = next((s for s in sessions if s["state"] == "in_progress"), None)
    pool = [s for s in complete if s["expected"] == FULL_SESSION_BARS
            and (before is None or dt.date.fromisoformat(s["date"]) < before)]
    f = meta.get("feed") or "iex"
    return {
        "provider": PROVIDER_ID, "feed": f, "adjustment": meta.get("adjustment"),
        "data_end": w.get("data_end"), "plan_day": w.get("plan_day"),
        "sessions_requested": w.get("sessions_requested"), "sessions": len(sessions),
        "closed_sessions": len(closed), "complete_sessions": len(complete),
        "early_close_sessions": sum(1 for s in complete if s["early_close"]),
        "incomplete_sessions": incomplete,
        "in_progress_session": in_progress,
        "not_started_sessions": [s["date"] for s in sessions if s["state"] == "not_started"],
        "missing_bars_closed": sum(s["missing"] for s in incomplete),
        "bars": len(stamps), "left_out": meta.get("leftOut") or {},
        "pool_sessions": len(pool), "engine_min_sessions": MIN_SESSIONS,
        "filled": False,
        "note": (("Feed IEX: horários sem negócio na IEX não têm candle" if f == "iex" else
                  "Feed SIP (consolidado): horários sem nenhum negócio não têm candle")
                 + " e não são preenchidos. Os motores usam só sessões encerradas com os 78 candles; as incompletas e "
                 "as de fechamento antecipado ficam de fora. Uma sessão em andamento é contada à parte e não entra "
                 "como incompleta."),
    }


def entry_bar_check(text: str, day: dt.date, entry_time: str) -> str | None:
    """Why the plan's entry bar is missing from an Alpaca snapshot, in plain words (None = present).
    entry_time is HH:MM, the close of the entry bar (as the Time Machine takes it)."""
    h, m = (int(x) for x in entry_time.split(":"))
    start = dt.datetime.combine(day, dt.time(h, m), mcal.NY) - dt.timedelta(minutes=5)
    ts = int(start.timestamp())
    doc = json.loads(text)
    r0 = doc["chart"]["result"][0]
    if ts in set(r0.get("timestamp") or []):
        return None
    w = (r0.get("meta") or {}).get("window") or {}
    if day.isoformat() not in (w.get("sessions") or []):
        return f"O snapshot não cobre {day.isoformat()}: ele vai de {w.get('sessions', ['?'])[0]} a {w.get('sessions', ['?'])[-1]}."
    data_end = _epoch(w.get("data_end", "1970-01-01T00:00:00Z"))
    label = start.strftime("%H:%M")
    if ts + BAR_S > data_end:
        return (f"O candle de entrada ({label}–{entry_time}) de {day.isoformat()} ainda não estava disponível: "
                "a sessão estava em andamento e o plano gratuito tem 15 minutos de atraso.")
    f = ((r0.get("meta") or {}).get("feed") or "iex").upper()
    return (f"O feed {f} não tem candle das {label} em {day.isoformat()}: não houve negócio nesse intervalo. "
            "O laboratório não preenche lacunas; escolha outro horário ou outro dia.")


# ---------------------------------------------------------------- one call for the jobs

def fetch_session_chart(symbol: str, day: dt.date | None, sessions: int = DEFAULT_SESSIONS,
                        now_utc: dt.datetime | None = None,
                        min_sessions: int = MIN_SESSIONS) -> tuple[str, dt.datetime, dict]:
    """5-minute bars for the window -> (chart text, fetched_at, quality). The feed is
    DP_ALPACA_FEED at call time; the caller records source(feed) on the snapshot."""
    f = feed()
    window = session_window(day, sessions, now_utc, min_sessions)
    fetched_at = (now_utc or _now()).replace(microsecond=0)
    # `end` is inclusive: stop one second before data_end so only complete bars come back.
    req_end = window.data_end - dt.timedelta(seconds=1)
    bars = providers.single_flight(
        (PROVIDER_ID, f, symbol, TIMEFRAME_5M, window.start.isoformat(), window.data_end.isoformat()),
        lambda: fetch_bars(symbol, TIMEFRAME_5M, window.start, req_end, f))
    if not bars:
        raise AlpacaError("no_data", f"A Alpaca não tem candles de {symbol} no feed {f.upper()} nesse período.")
    text = to_chart_document(symbol, bars, window, f)
    return text, fetched_at, session_quality(text)


def fetch_day_chart(symbol: str, day: dt.date, now_utc: dt.datetime | None = None) -> tuple[str, dt.datetime, dict]:
    """Only the plan day's regular session (Entry and Exit need no history): one call, about 80
    bars, up to the close or to now minus 16 minutes when the session is still open."""
    return fetch_session_chart(symbol, day, 0, now_utc, min_sessions=0)
