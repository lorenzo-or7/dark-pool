"""Data providers: what each one is, whether it may be used, and how much of its quota is left.

Every visitor of the public lab shares the same server, keys and quotas, so the limits live
here, in the process, and not in the browser:

- a per-minute window and a daily budget per provider, set below the published limits;
- a circuit breaker that pauses a provider after repeated failures or HTTP 429;
- single-flight: identical requests in progress are made once and shared.

State is in memory. That is enough for the single backend instance of the free Render plan;
a restart resets the counters (documented in docs/INTEGRACOES.md).

Provenance: `provenance_for_source(source)` describes the origin of a snapshot from its
`source` field, so existing snapshots keep their content hash.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import TypeVar
from zoneinfo import ZoneInfo

from ..config import get_settings

NY = ZoneInfo("America/New_York")
T = TypeVar("T")


class ProviderUnavailable(Exception):
    """A provider refused locally: disabled by policy, missing key, quota, or paused."""

    def __init__(self, provider: str, code: str, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.provider = provider
        self.code = code
        self.message = message
        self.retry_after = retry_after


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    use: str
    kind: str                     # "official", "unofficial", "library", "commercial"
    delay: str                    # what the data is: delayed, end of day, filings, computed...
    terms_url: str | None
    attribution: str | None
    per_minute: int | None        # local limit, below the published one
    per_day: int | None
    published_limit: str
    integrated: bool = True
    needs_key: bool = False
    unofficial: bool = False


PROVIDERS: dict[str, Provider] = {p.id: p for p in (
    Provider("yahoo", "Yahoo Finance (chart, spark e RSS)", "Candles, cotações, scanner diário e manchetes",
             "unofficial", "Cotações com atraso, sem garantia", "https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html",
             None, per_minute=60, per_day=3000, published_limit="não publicado (API não oficial)", unofficial=True),
    Provider("sec_edgar", "SEC EDGAR", "Fatos relevantes 8-K (News) e resultados XBRL (Analyst)", "official",
             "Documentos oficiais na data de arquivamento", "https://www.sec.gov/os/accessing-edgar-data",
             None, per_minute=300, per_day=20000, published_limit="10 requisições por segundo, com User-Agent"),
    Provider("nasdaq_trader", "Nasdaq Trader SymDir", "Universo de ações do Market Scanner", "official",
             "Listas atualizadas várias vezes ao dia", "https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs",
             None, per_minute=6, per_day=60, published_limit="não publicado"),
    Provider("exchange_calendars", "Calendário NYSE (exchange_calendars)", "Pregões, feriados e fechamentos antecipados",
             "library", "Calculado no servidor", "https://github.com/gerrymanoim/exchange_calendars",
             None, per_minute=None, per_day=None, published_limit="sem rede"),
    Provider("alpaca", "Alpaca Market Data (Basic)",
             "Candles de 5 min (Time Machine, backtests ORB, plano ORB) e cotações dos alertas, só para cálculo interno",
             "commercial", "Feed SIP (consolidado) com mais de 15 min no plano gratuito; IEX opcional",
             "https://alpaca.markets/disclosures",
             None, per_minute=150, per_day=None, published_limit="200 chamadas/min no histórico",
             needs_key=True),
)}

# Sources recorded on snapshots -> provider id.
SOURCE_PROVIDER = {"yahoo": "yahoo", "fixture:day-trader-skill/TSLA-60d5m": "yahoo", "alpaca:iex": "alpaca",
                   "alpaca:sip": "alpaca", "alpaca:delayed_sip": "alpaca"}


def bars_provider(interval: str) -> str:
    """Which provider supplies NEW bars of this interval (DP_INTRADAY_PROVIDER). Only the
    5-minute bars can come from Alpaca for now; daily and weekly bars stay on Yahoo until the
    daily rules are moved and compared (Bloco 6). No fallback: the caller checks the
    returned provider and fails if it is unavailable."""
    if interval != "5m":
        return "yahoo"
    s = get_settings()
    choice = s.dp_intraday_provider
    if choice == "auto":
        return "alpaca" if (s.alpaca_api_key_id and s.alpaca_api_secret_key) else "yahoo"
    return choice


def scan_provider() -> str:
    """Who supplies the scanner's bars (DP_SCAN_PROVIDER). No fallback."""
    s = get_settings()
    if s.dp_scan_provider == "auto":
        return "alpaca" if (s.alpaca_api_key_id and s.alpaca_api_secret_key) else "yahoo"
    return s.dp_scan_provider


def quote_provider() -> str:
    """Who supplies the alerts' quotes (DP_QUOTE_PROVIDER). No fallback."""
    s = get_settings()
    if s.dp_quote_provider == "auto":
        return "alpaca" if (s.alpaca_api_key_id and s.alpaca_api_secret_key) else "yahoo"
    return s.dp_quote_provider


def intraday_summary() -> dict:
    s = get_settings()
    pid = bars_provider("5m")
    return {"setting": s.dp_intraday_provider, "provider": pid,
            "feed": s.dp_alpaca_feed if pid == "alpaca" else None, "daily_provider": "yahoo"}


# ---------------------------------------------------------------- quota and circuit breaker

FAILURES_TO_PAUSE = 3
PAUSE_S = {"rate_limited": 120, "error": 30}


@dataclass
class _Gate:
    minute: deque = field(default_factory=deque)
    day: str = ""
    day_count: int = 0
    failures: int = 0
    paused_until: float = 0.0
    pause_reason: str | None = None
    last_success: float | None = None
    last_error: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


_gates: dict[str, _Gate] = {}
_gates_lock = threading.Lock()


def _gate(pid: str) -> _Gate:
    with _gates_lock:
        return _gates.setdefault(pid, _Gate())


def reset() -> None:
    """Tests only: forget counters, pauses and in-flight calls."""
    with _gates_lock:
        _gates.clear()
    with _flight_lock:
        _flights.clear()


def _today() -> str:
    return dt.datetime.now(NY).date().isoformat()


def check_allowed(pid: str) -> Provider:
    """Policy and configuration, without spending quota."""
    p = PROVIDERS[pid]
    s = get_settings()
    if p.unofficial and not s.allow_unofficial_sources:
        raise ProviderUnavailable(pid, "source_disabled",
                                  f"{p.name} está desativado neste laboratório: é uma fonte não oficial e seus "
                                  "termos não permitem uso automatizado em um site público.")
    if p.needs_key and not (s.alpaca_api_key_id and s.alpaca_api_secret_key):
        raise ProviderUnavailable(pid, "missing_key", f"{p.name} não tem chave configurada no servidor.")
    if not p.integrated:
        raise ProviderUnavailable(pid, "not_integrated", f"{p.name} ainda não está integrado.")
    return p


def acquire(pid: str, cost: int = 1) -> None:
    """Spend `cost` calls of the provider's quota, or raise ProviderUnavailable."""
    p = check_allowed(pid)
    g = _gate(pid)
    now = time.monotonic()
    with g.lock:
        if g.paused_until > now:
            wait = int(g.paused_until - now) + 1
            raise ProviderUnavailable(pid, "provider_paused",
                                      f"{p.name} está em pausa após falhas seguidas. Tente em {wait} s.", wait)
        today = _today()
        if g.day != today:
            g.day, g.day_count = today, 0
        if p.per_day is not None and g.day_count + cost > p.per_day:
            raise ProviderUnavailable(pid, "quota_exhausted",
                                      f"A cota diária do laboratório para {p.name} acabou. Ela volta amanhã "
                                      "(horário de Nova York).")
        while g.minute and now - g.minute[0] >= 60:
            g.minute.popleft()
        if p.per_minute is not None and len(g.minute) + cost > p.per_minute:
            wait = int(60 - (now - g.minute[0])) + 1 if g.minute else 60
            raise ProviderUnavailable(pid, "rate_limited",
                                      f"Muitas consultas a {p.name} neste minuto. Tente em {wait} s.", wait)
        g.minute.extend([now] * cost)
        g.day_count += cost


def success(pid: str) -> None:
    g = _gate(pid)
    with g.lock:
        g.failures = 0
        g.last_success = time.time()


def failure(pid: str, reason: str = "error") -> None:
    """Record a failed call. HTTP 429 pauses at once; other errors after FAILURES_TO_PAUSE in a row."""
    g = _gate(pid)
    with g.lock:
        g.failures += 1
        g.last_error = reason
        if reason == "rate_limited" or g.failures >= FAILURES_TO_PAUSE:
            g.paused_until = time.monotonic() + PAUSE_S.get(reason, PAUSE_S["error"])
            g.pause_reason = reason
            g.failures = 0


# ---------------------------------------------------------------- single flight

_flights: dict[tuple, Future] = {}
_flight_lock = threading.Lock()


def single_flight(key: tuple, fn: Callable[[], T]) -> T:
    """Run fn once for concurrent callers with the same key; the others get the same result."""
    with _flight_lock:
        fut = _flights.get(key)
        owner = fut is None
        if owner:
            fut = Future()
            _flights[key] = fut
    if not owner:
        return fut.result(timeout=120)
    try:
        result = fn()
    except BaseException as e:
        fut.set_exception(e)
        raise
    else:
        fut.set_result(result)
        return result
    finally:
        with _flight_lock:
            _flights.pop(key, None)


# ---------------------------------------------------------------- provenance and status

def provenance_for_source(source: str | None, is_fixture: bool = False) -> dict:
    pid = SOURCE_PROVIDER.get(source or "")
    p = PROVIDERS.get(pid) if pid else None
    if p is None:
        return {"provider": source, "provider_name": source, "official": None, "kind": "unknown",
                "delay": None, "terms_url": None, "attribution": None, "is_fixture": is_fixture}
    out = {"provider": p.id, "provider_name": p.name, "official": p.kind in ("official", "library"),
           "kind": p.kind, "delay": p.delay, "terms_url": p.terms_url, "attribution": p.attribution,
           "is_fixture": is_fixture or (source or "").startswith("fixture:")}
    if ":" in (source or "") and not (source or "").startswith("fixture:"):
        out["feed"] = source.split(":", 1)[1]
    return out


_STATUS_TEXT = {
    "active": ("ativo", "up"),
    "source_disabled": ("desativado pela política", "caution"),
    "missing_key": ("sem chave", "caution"),
    "not_integrated": ("ainda não integrado", "caution"),
    "provider_paused": ("pausado após falhas", "down"),
    "quota_exhausted": ("cota diária esgotada", "down"),
    "needs_config": ("requer SEC_USER_AGENT", "caution"),
}


def status() -> list[dict]:
    s = get_settings()
    out = []
    for p in PROVIDERS.values():
        g = _gate(p.id)
        code = "active"
        try:
            check_allowed(p.id)
        except ProviderUnavailable as e:
            code = e.code
        now = time.monotonic()
        with g.lock:
            if code == "active":
                if g.paused_until > now:
                    code = "provider_paused"
                elif p.per_day is not None and g.day == _today() and g.day_count >= p.per_day:
                    code = "quota_exhausted"
            if code == "active" and p.id == "sec_edgar" and not s.sec_user_agent:
                code = "needs_config"
            used_min = sum(1 for t in g.minute if now - t < 60)
            used_day = g.day_count if g.day == _today() else 0
            last_ok = g.last_success
        text, tone = _STATUS_TEXT[code]
        out.append({"id": p.id, "name": p.name, "use": p.use, "kind": p.kind, "official": p.kind in ("official", "library"),
                    "delay": p.delay, "terms_url": p.terms_url, "attribution": p.attribution,
                    "status_code": code, "status": text, "tone": tone,
                    "usage": {"minute": used_min, "per_minute": p.per_minute, "today": used_day, "per_day": p.per_day},
                    "published_limit": p.published_limit,
                    "last_success": dt.datetime.fromtimestamp(last_ok, dt.UTC).isoformat() if last_ok else None})
    return out
