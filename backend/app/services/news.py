"""News for one ticker (Bloco 7): SEC 8-K filings, GDELT headlines and coverage tone, and the
Yahoo headline RSS only where unofficial sources are allowed (off in the public lab).

trader-news is not edited. Its `collect` takes a fetcher with `get(url, name, sec=False)`; the
server passes its own fetcher, so every request goes through the shared quotas, the SEC gets the
configured User-Agent, and Yahoo answers "off" when the display policy disables unofficial
sources (the engine then records the error and goes on to the SEC part). The engine's own parsers
(parse_sec_atom, tag, dedupe) do the rest.

GDELT DOC 2.0 is not part of the skill: the server queries it by the company's name from the SEC
ticker list. Parameters as listed by the GDELT DOC 2.0 announcement
(https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/, which this build environment could not
open; checked against several client libraries): GET https://api.gdeltproject.org/api/v2/doc/doc
with query, mode=ArtList | TimelineTone, format=json, maxrecords (<= 250), timespan, sort=DateDesc;
ArtList articles carry url, title, seendate (YYYYMMDDTHHMMSSZ), domain, language, sourcecountry.
Every headline keeps its link and the outlet; GDELT is cited wherever its items appear. The tone is
GDELT's own average tone of the coverage, shown as a number, never turned into a recommendation.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import threading
import time
from pathlib import Path

import httpx

from ..config import get_settings
from ..engines.runner import load_module
from . import market_data as md
from . import providers

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_ATTRIBUTION = "Manchetes e tom: GDELT Project (gdeltproject.org). Cada manchete leva ao texto original."
TICKERS_TTL = 24 * 3600
GDELT_TTL = 15 * 60
SUFFIXES = re.compile(r"[,.]?\s+(inc|incorporated|corp|corporation|co|company|ltd|limited|plc|holdings?|group|"
                      r"n\.?v|s\.?a|ag|se|lp|l\.?p|llc|the)\.?$", re.I)

_lock = threading.Lock()
_tickers: dict = {"at": 0.0, "raw": None, "map": {}}
_gdelt_cache: dict[tuple, tuple[float, object]] = {}


class NewsError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _cache_file() -> Path:
    p = Path(get_settings().dp_data_dir) / "cache" / "sec_company_tickers.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------- network (tests replace these two)

def _sec_get(url: str, ua: str) -> httpx.Response:
    return httpx.get(url, headers={"User-Agent": ua, "Accept-Encoding": "gzip"}, timeout=30)


def _http_get(url: str, params: dict | None = None) -> httpx.Response:
    return httpx.get(url, params=params, headers={"User-Agent": md.UA}, timeout=30)


# ---------------------------------------------------------------- SEC

def sec_fetch(url: str) -> bytes:
    ua = get_settings().sec_user_agent
    if not ua:
        raise NewsError("needs_config", "Configure SEC_USER_AGENT (\"Nome email\") no backend para ler a SEC.")
    try:
        providers.acquire("sec_edgar")
    except providers.ProviderUnavailable as e:
        raise NewsError(e.code, e.message)
    try:
        r = _sec_get(url, ua)
    except httpx.HTTPError as e:
        providers.failure("sec_edgar")
        raise NewsError("provider_unreachable", f"Não foi possível acessar a SEC ({type(e).__name__}).")
    if r.status_code == 429 or r.status_code == 403:
        providers.failure("sec_edgar", "rate_limited" if r.status_code == 429 else None)
        raise NewsError("rate_limited" if r.status_code == 429 else "provider_auth",
                        f"A SEC recusou o pedido (HTTP {r.status_code}). Confira o SEC_USER_AGENT.")
    if r.status_code != 200:
        providers.failure("sec_edgar")
        raise NewsError("provider_error", f"A SEC respondeu HTTP {r.status_code}.")
    providers.success("sec_edgar")
    return r.content


def company_tickers() -> tuple[bytes, dict[str, dict]]:
    """SEC's company_tickers.json (raw bytes for the engine, {TICKER: {cik, title}} for the server),
    downloaded at most once a day per server and kept on disk."""
    with _lock:
        if _tickers["raw"] is not None and time.time() - _tickers["at"] < TICKERS_TTL:
            return _tickers["raw"], _tickers["map"]
        f = _cache_file()
        raw = None
        if f.exists() and time.time() - f.stat().st_mtime < TICKERS_TTL:
            raw = f.read_bytes()
        if raw is None:
            raw = sec_fetch(SEC_TICKERS_URL)
            f.write_bytes(raw)
        try:
            data = json.loads(raw.decode("utf-8"))
            mp = {str(v["ticker"]).upper().replace("-", "."): {"cik": str(v["cik_str"]).zfill(10),
                                                              "title": str(v.get("title") or "")}
                  for v in data.values()}
        except (ValueError, KeyError, AttributeError, TypeError):
            raise NewsError("bad_payload", "A lista de tickers da SEC veio num formato inesperado.")
        _tickers.update(at=time.time(), raw=raw, map=mp)
        return raw, mp


def query_name(title: str) -> str:
    """'Tesla, Inc.' -> 'Tesla'; 'Apple Inc.' -> 'Apple'. Suffixes only; nothing else is guessed."""
    name = title.strip()
    for _ in range(3):
        new = SUFFIXES.sub("", name).strip(" ,.")
        if new == name:
            break
        name = new
    return name


class ServerFetcher:
    """What trader-news' collect() calls: SEC through the shared quota with the User-Agent; Yahoo RSS
    only when unofficial sources are allowed; anything else refused."""

    def __init__(self, engine):  # noqa: ANN001
        self.engine = engine
        self.yahoo_calls = 0

    def get(self, url: str, name: str, sec: bool = False) -> bytes:
        if url == SEC_TICKERS_URL:
            try:
                return company_tickers()[0]
            except NewsError as e:
                raise self.engine.NewsError(e.message)
        if sec:
            try:
                return sec_fetch(url)
            except NewsError as e:
                raise self.engine.NewsError(e.message)
        if url.startswith("https://feeds.finance.yahoo.com/"):
            try:
                providers.acquire(md.PROVIDER_ID)
            except providers.ProviderUnavailable as e:
                raise self.engine.NewsError("yahoo_off: " + e.message)
            self.yahoo_calls += 1
            try:
                r = _http_get(url)
            except httpx.HTTPError as e:
                providers.failure(md.PROVIDER_ID)
                raise self.engine.NewsError(f"Yahoo RSS inacessível ({type(e).__name__})")
            if r.status_code != 200:
                providers.failure(md.PROVIDER_ID)
                raise self.engine.NewsError(f"Yahoo RSS respondeu HTTP {r.status_code}")
            providers.success(md.PROVIDER_ID)
            return r.content
        raise self.engine.NewsError("endereço não permitido pelo servidor")


# ---------------------------------------------------------------- GDELT

def _gdelt(params: dict) -> dict:
    key = tuple(sorted(params.items()))
    with _lock:
        hit = _gdelt_cache.get(key)
        if hit and time.time() - hit[0] < GDELT_TTL:
            return hit[1]  # type: ignore[return-value]
    try:
        providers.acquire("gdelt")
    except providers.ProviderUnavailable as e:
        raise NewsError(e.code, e.message)
    try:
        r = _http_get(GDELT_URL, params)
    except httpx.HTTPError as e:
        providers.failure("gdelt")
        raise NewsError("provider_unreachable", f"Não foi possível acessar o GDELT ({type(e).__name__}).")
    if r.status_code == 429:
        providers.failure("gdelt", "rate_limited")
        raise NewsError("rate_limited", "O GDELT está limitando requisições (HTTP 429). Tente em um minuto.")
    if r.status_code != 200:
        providers.failure("gdelt")
        raise NewsError("provider_error", f"O GDELT respondeu HTTP {r.status_code}.")
    text = r.text.strip()
    if not text:
        doc: dict = {}
    else:
        try:
            doc = json.loads(text)
        except ValueError:
            # GDELT answers plain text when asked too often ("Please limit requests...") or for a bad query.
            providers.failure("gdelt", "rate_limited" if "limit" in text.lower() else None)
            raise NewsError("rate_limited" if "limit" in text.lower() else "provider_bad_request",
                            "O GDELT recusou a consulta: " + text[:160])
    providers.success("gdelt")
    with _lock:
        _gdelt_cache[key] = (time.time(), doc)
    return doc


def _seen(v: str) -> str | None:
    try:
        return dt.datetime.strptime(v, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.UTC).isoformat()
    except (TypeError, ValueError):
        return None


def gdelt_headlines(name: str, timespan: str = "7d", maxrecords: int = 25) -> list[dict]:
    doc = _gdelt({"query": f'"{name}" sourcelang:english', "mode": "ArtList", "format": "json",
                  "maxrecords": str(maxrecords), "timespan": timespan, "sort": "DateDesc"})
    out = []
    for a in (doc.get("articles") or [])[:maxrecords]:
        url, title = a.get("url"), (a.get("title") or "").strip()
        if not url or not title or not str(url).startswith(("https://", "http://")):
            continue
        out.append({"id": "gdelt:" + url, "provider": "gdelt", "source": a.get("domain") or "",
                    "kind": "headline", "title": title, "summary": "", "link": url, "time": _seen(a.get("seendate")),
                    "language": a.get("language"), "sourcecountry": a.get("sourcecountry")})
    return out


def gdelt_tone(name: str, timespan: str = "7d") -> dict | None:
    """GDELT's average tone of the coverage over the window (TimelineTone), as GDELT computes it."""
    doc = _gdelt({"query": f'"{name}" sourcelang:english', "mode": "TimelineTone", "format": "json",
                  "timespan": timespan})
    pts = []
    for series in doc.get("timeline") or []:
        for d in series.get("data") or []:
            v = d.get("value")
            if isinstance(v, (int, float)):
                pts.append(float(v))
    if not pts:
        return None
    return {"average": round(sum(pts) / len(pts), 3), "points": len(pts), "timespan": timespan,
            "label": "Tom médio da cobertura segundo o GDELT (negativo = cobertura mais negativa). "
                     "É uma medida do texto das notícias, não uma previsão de preço."}


# ---------------------------------------------------------------- one ticker

def build(symbol: str, hours: int = 168) -> dict:
    s = get_settings()
    nw = load_module("news")
    errors: list[str] = []
    notes: list[str] = []
    sources: list[str] = []
    ua = s.sec_user_agent
    company = None
    if ua:
        try:
            company = company_tickers()[1].get(symbol)
        except NewsError as e:
            errors.append(f"SEC: {e.message}")
    else:
        notes.append("Filings 8-K da SEC e manchetes do GDELT desativados: configure SEC_USER_AGENT (\"Nome email\") "
                     "no backend. O nome da empresa para o GDELT vem da lista da SEC.")
    fetcher = ServerFetcher(nw)
    eng_errors: list[str] = []
    items = nw.collect(fetcher, {symbol: company["title"] if company else None}, {}, sec=bool(ua),
                       forms=("8-K",), count=10, errors=eng_errors)
    yahoo_on = s.allow_unofficial_sources
    for e in eng_errors:
        if "yahoo_off" in e:
            continue  # the policy, not a failure: said once in the notes
        errors.append(e)
    if not yahoo_on:
        notes.append("Manchetes do Yahoo Finance desligadas (fonte não oficial; os termos não permitem uso "
                     "automatizado em site público). Manchetes vêm do GDELT, com link para o texto original.")
    if ua:
        sources.append("SEC EDGAR (8-K)")
    if fetcher.yahoo_calls:
        sources.append("Yahoo Finance RSS")
    tone = None
    if company:
        name = query_name(company["title"])
        try:
            g = gdelt_headlines(name)
            for it in g:
                it["ticker"] = symbol
                it["time"] = nw.parse_time(it["time"]) if it["time"] else None
            items += g
            tone = gdelt_tone(name)
            sources.append("GDELT")
        except NewsError as e:
            errors.append(f"GDELT: {e.message}")
    elif ua and company is None:
        notes.append(f"{symbol} não está na lista de tickers da SEC: sem 8-K nem consulta ao GDELT.")
    items = nw.dedupe(nw.tag(items, {symbol: company["title"] if company else None}))
    now = dt.datetime.now(dt.UTC)
    cutoff = now - dt.timedelta(hours=hours)
    items = [it for it in items if it.get("time") is None or it["time"] >= cutoff]
    items.sort(key=lambda it: it.get("time") or dt.datetime.min.replace(tzinfo=dt.UTC), reverse=True)
    return {
        "symbol": symbol, "company": company["title"] if company else None,
        "items": nw._json_ready(items), "coverage_tone": tone, "errors": errors, "notes": notes,
        "sources": sources, "sec_included": bool(ua), "yahoo_included": bool(fetcher.yahoo_calls),
        "attribution": GDELT_ATTRIBUTION if "GDELT" in sources else None,
        "note": " ".join(notes) or None,
        "disclaimer": "Manchetes e filings são pistas, não fatos verificados nem recomendação.",
    }
