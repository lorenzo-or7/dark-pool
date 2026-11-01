"""SEC metadata of a listed company (Bloco 8): CIK, exchanges, SIC code and the SIC division as
the sector. Official sources only; nothing estimated.

- CIK and registered name: https://www.sec.gov/files/company_tickers.json (services/news.py keeps
  it, downloaded at most once a day).
- Exchanges, SIC, fiscal year end, filer category: https://data.sec.gov/submissions/CIK##########.json
  (documented at https://www.sec.gov/edgar/sec-api-documentation: "metadata such as current name,
  former name, and stock exchanges and ticker symbols"; the `sic`, `sicDescription`, `category`,
  `fiscalYearEnd` and `stateOfIncorporation` field names are the ones every client library reads;
  the skill's saved submissions file is an excerpt without them). Cached on disk for 7 days.
- Sector = the SIC division of the 4-digit code (Standard Industrial Classification Manual,
  https://www.osha.gov/data/sic-manual). Nothing finer is inferred.
- Market cap is not computed here and float is out of scope (decided in the provider report).
"""

from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path

from ..config import get_settings
from . import news

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
TTL = 7 * 24 * 3600

# SIC divisions by the first two digits (SIC Manual, OSHA).
SIC_DIVISIONS = [
    ((1, 9), "A", "Agricultura, silvicultura e pesca"),
    ((10, 14), "B", "Mineração"),
    ((15, 17), "C", "Construção"),
    ((20, 39), "D", "Indústria de transformação"),
    ((40, 49), "E", "Transporte, comunicações, energia, gás e saneamento"),
    ((50, 51), "F", "Comércio atacadista"),
    ((52, 59), "G", "Comércio varejista"),
    ((60, 67), "H", "Finanças, seguros e imóveis"),
    ((70, 89), "I", "Serviços"),
    ((91, 97), "J", "Administração pública"),
    ((99, 99), "K", "Não classificável"),
]


def sic_division(code: str | int | None) -> dict | None:
    try:
        n = int(str(code).strip())
    except (TypeError, ValueError):
        return None
    if not 100 <= n <= 9999:
        return None
    two = n // 100
    for (lo, hi), letter, name in SIC_DIVISIONS:
        if lo <= two <= hi:
            return {"division": letter, "name": name, "sic_range": f"{lo:02d}{'' if lo == hi else f'–{hi:02d}'}"}
    return None


def _cache_path(cik: str) -> Path:
    p = Path(get_settings().dp_data_dir) / "cache" / "sec_submissions" / f"CIK{cik}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def submissions(cik: str) -> tuple[dict, dt.datetime, bool]:
    """-> (submissions JSON without the filings list, fetched_at, from_cache)."""
    p = _cache_path(cik)
    if p.exists() and time.time() - p.stat().st_mtime < TTL:
        return json.loads(p.read_text(encoding="utf-8")), dt.datetime.fromtimestamp(p.stat().st_mtime, dt.UTC), True
    raw = news.sec_fetch(SUBMISSIONS_URL.format(cik=cik))
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise news.NewsError("bad_payload", "A SEC devolveu um formato inesperado.")
    if not isinstance(doc, dict):
        raise news.NewsError("bad_payload", "A SEC devolveu um formato inesperado.")
    doc.pop("filings", None)   # the filing history is large and not needed here
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return doc, dt.datetime.now(dt.UTC), False


def profile(symbol: str) -> dict:
    _, mp = news.company_tickers()
    hit = mp.get(symbol)
    if hit is None:
        raise news.NewsError("unknown_symbol", f"{symbol} não está na lista de tickers da SEC.")
    cik = hit["cik"]
    doc, fetched, cached = submissions(cik)
    sic = str(doc.get("sic") or "").strip() or None
    return {
        "symbol": symbol, "cik": cik, "name": doc.get("name") or hit["title"],
        "tickers": doc.get("tickers") or [], "exchanges": doc.get("exchanges") or [],
        "sic": sic, "sic_description": doc.get("sicDescription") or None, "sector": sic_division(sic),
        "fiscal_year_end": doc.get("fiscalYearEnd") or None, "category": doc.get("category") or None,
        "state_of_incorporation": doc.get("stateOfIncorporation") or None,
        "entity_type": doc.get("entityType") or None,
        "source": "SEC EDGAR (company_tickers.json e submissions)",
        "sec_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}",
        "fetched_at": fetched.isoformat(), "from_cache": cached,
        "notes": ["Setor = divisão da classificação SIC informada pela empresa à SEC (Manual SIC). "
                  "Valor de mercado e free float não são exibidos."],
    }
