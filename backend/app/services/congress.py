"""Congress trades (Bloco 10): House Periodic Transaction Reports through trader-pelosi.

trader-pelosi is not edited. The server downloads the House Clerk's public files through the shared
quota and hands the bytes and the text to the engine's own parsers (read_index_bytes, parse_index,
select, parse_ptr_text):
  index  https://disclosures-clerk.house.gov/public_disc/financial-pdfs/<YEAR>FD.zip (cached 6 hours)
  a PTR  https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/<YEAR>/<DocID>.pdf (cached for good:
         a filed document does not change), turned into text with `pdftotext -layout` (poppler) by
         the engine's pdf_to_text. Without pdftotext on the server, the answer has the filing, its
         dates and the PDF link, and says the rows could not be read.

Three dates are kept apart: the trade date (`date` of each row), the document date (`filed`) and the
collection time (`collected_at`). Amounts are the ranges the form uses. The Senate is not covered:
its reports sit behind an agreement a person must accept at https://efdsearch.senate.gov/search/,
which the lab does not automate.

Display policy: in the public lab these answers are off unless DP_PELOSI_PUBLIC=true (waiting for the
legal review of 5 U.S.C. 13107(c)); the local demo shows them.
"""

from __future__ import annotations

import datetime as dt
import time
from pathlib import Path

import httpx

from ..config import get_settings
from ..engines.runner import load_module
from . import providers

INDEX_TTL = 6 * 3600
PID = "house_clerk"
SENATE = {"covered": False, "url": "https://efdsearch.senate.gov/search/",
          "note": "Senado não coberto: os relatórios ficam atrás de um termo que cada pessoa aceita no eFD; "
                  "o laboratório não automatiza esse aceite."}
DISCLAIMER = ("Divulgação pública obrigatória (STOCK Act), feita dias ou semanas depois da operação e com valores em "
              "faixas. Não é informação privilegiada nem recomendação.")


class CongressError(Exception):
    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def allowed() -> bool:
    s = get_settings()
    return (not s.is_public) or s.dp_pelosi_public


def require_allowed() -> None:
    if not allowed():
        raise CongressError("display_policy", "As operações de parlamentares não são exibidas neste laboratório público "
                                              "até o parecer jurídico sobre o uso comercial (5 U.S.C. §13107(c)).", 403)


def _cache(name: str) -> Path:
    p = Path(get_settings().dp_data_dir) / "cache" / "house_clerk" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _http_get(url: str) -> httpx.Response:
    """The only network call (tests replace it)."""
    pt = load_module("pelosi")
    return httpx.get(url, headers={"User-Agent": pt.UA}, timeout=60, follow_redirects=False)


def _download(url: str) -> bytes:
    try:
        providers.acquire(PID)
    except providers.ProviderUnavailable as e:
        raise CongressError(e.code, e.message, 503)
    try:
        r = _http_get(url)
    except httpx.HTTPError as e:
        providers.failure(PID)
        raise CongressError("provider_unreachable", f"Não foi possível acessar a House Clerk ({type(e).__name__}).")
    if r.status_code == 404:
        providers.success(PID)
        raise CongressError("not_found", "A House Clerk não tem esse arquivo.", 404)
    if r.status_code != 200:
        providers.failure(PID, "rate_limited" if r.status_code == 429 else None)
        raise CongressError("provider_error", f"A House Clerk respondeu HTTP {r.status_code}.")
    providers.success(PID)
    return r.content


def index(year: int, members: list[str] | None = None, since: str | None = None, limit: int = 100) -> dict:
    require_allowed()
    pt = load_module("pelosi")
    f = _cache(f"{year}FD.zip")
    cached = f.exists() and time.time() - f.stat().st_mtime < INDEX_TTL
    if not cached:
        f.write_bytes(_download(pt.INDEX_URL % (year, "FD")))
    collected = dt.datetime.fromtimestamp(f.stat().st_mtime, dt.UTC).isoformat()
    try:
        rows = pt.parse_index(pt.read_index_bytes(f.read_bytes()), year)
    except pt.PtrError as e:
        f.unlink(missing_ok=True)
        raise CongressError("bad_payload", f"O índice da House Clerk veio num formato inesperado: {e}")
    sel = pt.select(rows, members or None, "P", since)
    return {"year": year, "filings": [{**r, "collected_at": collected} for r in sel[:limit]], "total": len(sel),
            "collected_at": collected, "from_cache": cached, "source": "House Clerk (índice <ANO>FD.zip)",
            "source_url": pt.INDEX_URL % (year, "FD"), "senate": SENATE, "disclaimer": DISCLAIMER}


def _pdf_text(path: Path) -> str | None:
    """The engine's own pdftotext call (None when poppler is not installed). Tests replace it."""
    return load_module("pelosi").pdf_to_text(str(path))


def report(doc_id: str, year: int, filed: str | None = None) -> dict:
    require_allowed()
    if not doc_id.isdigit() or len(doc_id) > 12:
        raise CongressError("invalid_doc_id", "DocID inválido.", 400)
    pt = load_module("pelosi")
    url = pt.PTR_URL % (year, doc_id)
    f = _cache(f"{year}-{doc_id}.pdf")
    cached = f.exists()
    if not cached:
        f.write_bytes(_download(url))
    collected = dt.datetime.fromtimestamp(f.stat().st_mtime, dt.UTC).isoformat()
    text = _pdf_text(f)
    out = {"doc_id": doc_id, "year": year, "pdf_url": url, "collected_at": collected, "from_cache": cached,
           "senate": SENATE, "disclaimer": DISCLAIMER, "source": "House Clerk (PTR em PDF)"}
    if text is None:
        return {**out, "filed": filed, "rows": None, "readable": False,
                "note": "O servidor não tem o pdftotext (poppler) para ler o PDF. Abra o documento pelo link."}
    parsed = pt.parse_ptr_text(text, filed)
    return {**out, "readable": True, "name": parsed.get("name"), "status": parsed.get("status"),
            "district": parsed.get("district"), "filed": parsed.get("filed"), "rows": parsed.get("rows") or [],
            "dates_note": "date = data da operação; notified = data em que o parlamentar foi avisado; filed = data do "
                          "documento; collected_at = coleta pelo laboratório.",
            "note": None if parsed.get("rows") else "Nenhuma linha de operação reconhecida no PDF; confira o documento."}
