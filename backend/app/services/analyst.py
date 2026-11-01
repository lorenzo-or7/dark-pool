"""Reported results of one company (Bloco 9): trader-analyst on SEC data, with the server's fetcher.

trader-analyst is not edited. Its pure functions (ticker_ciks, analyse, latest_filings, changes,
stale_note) read through a fetcher with `json(url, name)`; the server passes its own, so every SEC
request goes through the shared quota with SEC_USER_AGENT and is cached on disk:
companyfacts and submissions for 12 hours, a filing's index.json for 30 days (filed documents do
not change), the ticker list once a day (services/news.py).

"Next results" is shown only as HISTORY: the dates on which the company filed an 8-K with item 2.02
(results of operations), from the submissions file. The lab does not estimate a future date.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from pathlib import Path

from ..config import get_settings
from ..engines.runner import load_module
from . import news

FRESH_TTL = 12 * 3600
INDEX_TTL = 30 * 24 * 3600
HISTORY = 12   # earnings 8-Ks listed


class AnalystError(Exception):
    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _cache_path(url: str) -> Path:
    key = hashlib.sha256(url.encode()).hexdigest()[:32]
    p = Path(get_settings().dp_data_dir) / "cache" / "sec_analyst" / f"{key}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


class ServerFactsFetcher:
    """What trader-analyst calls: SEC JSON through the shared quota, cached on disk."""

    def __init__(self, engine):  # noqa: ANN001
        self.engine = engine
        self.requests = 0
        self.cached = 0

    def json(self, url: str, name: str):  # noqa: ANN201
        if url == news.SEC_TICKERS_URL:
            try:
                return json.loads(news.company_tickers()[0].decode("utf-8"))
            except news.NewsError as e:
                raise self.engine.FactsError(e.message)
        if not url.startswith(("https://data.sec.gov/", "https://www.sec.gov/")):
            raise self.engine.FactsError("endereço não permitido pelo servidor")
        p = _cache_path(url)
        ttl = INDEX_TTL if url.endswith("/index.json") else FRESH_TTL
        if p.exists() and time.time() - p.stat().st_mtime < ttl:
            self.cached += 1
            return json.loads(p.read_text(encoding="utf-8"))
        try:
            raw = news.sec_fetch(url)
        except news.NewsError as e:
            if e.code == "provider_error" and "404" in e.message:
                raise self.engine.FactsError(f"a SEC não tem dados em {url} (sem XBRL para este CIK?)")
            raise self.engine.FactsError(e.message)
        self.requests += 1
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise self.engine.FactsError("a SEC devolveu um formato inesperado")
        p.write_text(json.dumps(doc), encoding="utf-8")
        return doc


def earnings_history(submissions: dict, cik: str, limit: int = HISTORY) -> list[dict]:
    """8-Ks with item 2.02 (results of operations), newest first, from the submissions file."""
    rec = (submissions.get("filings") or {}).get("recent") or {}
    forms = rec.get("form") or []
    items = rec.get("items") or [""] * len(forms)
    out = []
    base = int(cik)
    for i, form in enumerate(forms):
        if form != "8-K" or "2.02" not in str(items[i] if i < len(items) else ""):
            continue
        acc = rec["accessionNumber"][i]
        folder = f"https://www.sec.gov/Archives/edgar/data/{base}/{acc.replace('-', '')}/"
        out.append({"filed": rec["filingDate"][i], "event_date": (rec.get("reportDate") or [None] * len(forms))[i] or None,
                    "accession": acc, "items": str(items[i]),
                    "url": folder + rec["primaryDocument"][i], "index": folder + f"{acc}-index.htm"})
        if len(out) >= limit:
            break
    return out


def build(symbol: str, quarters: int = 6) -> dict:
    if not get_settings().sec_user_agent:
        raise AnalystError("sec_user_agent_missing", "A SEC exige SEC_USER_AGENT (nome e e-mail) no backend.", 424)
    fa = load_module("analyst")
    f = ServerFactsFetcher(fa)
    try:
        ciks = fa.ticker_ciks(f)
    except fa.FactsError as e:
        raise AnalystError("provider_error", str(e))
    cik, name = ciks.get(symbol, (None, None))
    if not cik:
        raise AnalystError("unknown_symbol", f"{symbol} não tem CIK na SEC (ETFs e emissores estrangeiros podem não ter "
                                             "dados XBRL).", 404)
    try:
        cf = f.json(fa.FACTS_URL % cik, f"companyfacts-CIK{cik}.json")
        result = fa.analyse(cf, quarters=quarters, name=name)
        sub = f.json(fa.SUBMISSIONS_URL % cik, f"submissions-CIK{cik}.json")
        filings = fa.latest_filings(sub, cik, f)
    except fa.FactsError as e:
        msg = str(e)
        raise AnalystError("no_xbrl" if "sem XBRL" in msg else "provider_error", msg,
                           422 if "sem XBRL" in msg else 502)
    return {
        "symbol": symbol, "ticker": symbol, "result": result, "filings": filings, "changes": fa.changes(result),
        "note": fa.stale_note(result, filings),
        "earnings_history": earnings_history(sub, cik),
        "earnings_history_note": ("Datas em que a empresa arquivou um 8-K com o item 2.02 (resultados). É histórico: o "
                                  "laboratório não estima a data do próximo resultado."),
        "source": "SEC EDGAR (XBRL company facts e submissions)",
        "sec": {"requests": f.requests, "from_cache": f.cached},
        "fetched_at": dt.datetime.now(dt.UTC).isoformat(),
        "disclaimer": "Números reportados à SEC. O laboratório nunca diz se uma ação é compra.",
    }
