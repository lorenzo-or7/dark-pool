"""Bloco 10: House PTRs (House Clerk) through trader-pelosi.

Data used here, all from the skill's own test folder (backend/vendor/day_trader_skill/tests/fixtures/trader-pelosi):
- 2026FD.zip: a saved House Clerk index (an excerpt of the real <YEAR>FD.zip, with its BOM);
- ptr-*.txt: `pdftotext -layout` output of real PTRs (two complete, two excerpts).
The PDF bytes are NOT real: the fake House Clerk below answers b"%PDF-1.7 ..." stand-ins (marked as such) and
the fake `_pdf_text` returns the matching saved text. Nothing here reaches the network.

Oracles: the engine itself. The index must equal the engine's command line
(`ptr.py index --year 2026 --member pelosi --offline 2026FD.zip --json`) plus `collected_at`; the rows must
equal `parse_ptr_text(text, filed)`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from .conftest import DEMO, _reset

SKILL = Path(__file__).resolve().parents[1] / "vendor" / "day_trader_skill"
PTR_PY = SKILL / "trader-pelosi" / "ptr.py"
FIX = SKILL / "tests" / "fixtures" / "trader-pelosi"
ZIP = FIX / "2026FD.zip"
TEXTS = {"20035143": "ptr-20035143.txt", "20035590": "ptr-20035590.txt",
         "20035562": "ptr-20035562-excerpt.txt", "20033725": "ptr-20033725-excerpt.txt"}
INDEX_URL = "https://disclosures-clerk.house.gov/public_disc/financial-pdfs/2026FD.zip"
PTR_URL = "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/%s.pdf"


def fake_pdf(doc_id: str) -> bytes:
    """NOT a real PDF: a stand-in that only carries the magic bytes the service checks."""
    return b"%PDF-1.7\n% test stand-in for House PTR " + doc_id.encode() + b" (not a real PDF)\n"


class House:
    """The House Clerk as the tests see it: the saved index, stand-in PDFs, 404 for anything else."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.override: dict[str, httpx.Response] = {}

    def __call__(self, url: str) -> httpx.Response:
        self.calls.append(url)
        req = httpx.Request("GET", url)
        if url in self.override:
            return self.override[url]
        if url == INDEX_URL:
            return httpx.Response(200, content=ZIP.read_bytes(), request=req)
        for doc in TEXTS:
            if url == PTR_URL % doc:
                return httpx.Response(200, content=fake_pdf(doc), request=req)
        return httpx.Response(404, request=req)


def text_for(path: Path) -> str | None:
    doc = path.stem.split("-", 1)[1]
    assert path.read_bytes() == fake_pdf(doc)             # the service hands over the cached file
    return (FIX / TEXTS[doc]).read_text(encoding="utf-8")


def engine():  # noqa: ANN201
    from app.engines.runner import load_module
    return load_module("pelosi")


def cli(*args: str) -> list[dict]:
    """The engine's own command line, run as the skill documents it (isolated interpreter)."""
    out = subprocess.run([sys.executable, "-I", str(PTR_PY), "index", "--year", "2026", "--offline", str(ZIP),
                          "--json", *args], capture_output=True, text=True, timeout=60, check=True)
    return json.loads(out.stdout)


@pytest.fixture()
def house(settings_env: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, House]]:
    from app.main import create_app
    from app.services import congress
    h = House()
    monkeypatch.setattr(congress, "_http_get", h)
    monkeypatch.setattr(congress, "_pdf_text", text_for)
    with TestClient(create_app()) as c:
        yield c, h


def _no_collected(rows: list[dict]) -> list[dict]:
    return [{k: v for k, v in r.items() if k != "collected_at"} for r in rows]


# ---------------------------------------------------------------- the index

def test_index_equals_the_engine_command_line(house: tuple[TestClient, House]) -> None:
    c, h = house
    r = c.get("/api/congress/ptrs", params={"year": 2026, "member": "pelosi"}, headers=DEMO)
    assert r.status_code == 200, r.text
    d = r.json()
    oracle = cli("--member", "pelosi")
    assert [f["doc_id"] for f in oracle] == ["20035553", "20035143", "20034836", "20033725"]
    assert _no_collected(d["filings"]) == oracle
    assert all(f["collected_at"] == d["collected_at"] for f in d["filings"])
    assert d["total"] == 4 and d["year"] == 2026 and d["from_cache"] is False
    assert d["source_url"] == INDEX_URL and h.calls == [INDEX_URL]
    # the three dates kept apart: the document date per filing, the collection time for the answer
    assert d["filings"][1]["filed"] == "2026-08-21" and d["collected_at"].endswith("+00:00")
    assert d["senate"] == {"covered": False, "url": "https://efdsearch.senate.gov/search/", "note": d["senate"]["note"]}
    assert "eFD" in d["senate"]["note"] and "STOCK Act" in d["disclaimer"]


def test_index_is_cached_six_hours(house: tuple[TestClient, House], settings_env: Path) -> None:
    from app.services import congress
    c, h = house
    first = c.get("/api/congress/ptrs", params={"year": 2026}, headers=DEMO).json()
    again = c.get("/api/congress/ptrs", params={"year": 2026, "member": "Nancy Pelosi"}, headers=DEMO).json()
    assert h.calls == [INDEX_URL]                                         # no new download
    assert again["from_cache"] is True and again["collected_at"] == first["collected_at"]
    assert _no_collected(again["filings"]) == cli("--member", "Nancy Pelosi")
    cached = settings_env / "data" / "cache" / "house_clerk" / "2026FD.zip"
    assert cached.read_bytes() == ZIP.read_bytes()
    old = cached.stat().st_mtime - congress.INDEX_TTL - 1                 # older than 6 h: downloaded again
    os.utime(cached, (old, old))
    third = c.get("/api/congress/ptrs", params={"year": 2026}, headers=DEMO).json()
    assert h.calls == [INDEX_URL, INDEX_URL] and third["from_cache"] is False


def test_since_filter_and_limit(house: tuple[TestClient, House]) -> None:
    c, _ = house
    d = c.get("/api/congress/ptrs", params={"year": 2026, "since": "2026-10-07"}, headers=DEMO).json()
    oracle = cli("--since", "2026-10-07")
    assert _no_collected(d["filings"]) == oracle and d["total"] == len(oracle) == 5
    assert d["filings"][0]["filed"] == "2026-10-12" and all(f["type"] == "P" for f in d["filings"])
    d = c.get("/api/congress/ptrs", params={"year": 2026, "limit": 2}, headers=DEMO).json()
    assert len(d["filings"]) == 2 and d["total"] == len(cli("--limit", "500"))
    r = c.get("/api/congress/ptrs", params={"year": 2026, "since": "07/10/2026"}, headers=DEMO)
    assert r.status_code == 422


def test_index_errors(house: tuple[TestClient, House], settings_env: Path) -> None:
    c, h = house
    r = c.get("/api/congress/ptrs", params={"year": 2027}, headers=DEMO)  # the Clerk has no 2027 index
    assert r.status_code == 404 and r.json()["detail"]["code"] == "not_found"
    assert not (settings_env / "data" / "cache" / "house_clerk" / "2027FD.zip").exists()
    h.override[INDEX_URL] = httpx.Response(200, content=b"not a zip and not xml", request=httpx.Request("GET", INDEX_URL))
    r = c.get("/api/congress/ptrs", params={"year": 2026}, headers=DEMO)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "bad_payload"
    assert not (settings_env / "data" / "cache" / "house_clerk" / "2026FD.zip").exists()   # bad file not kept
    h.override[INDEX_URL] = httpx.Response(500, request=httpx.Request("GET", INDEX_URL))
    r = c.get("/api/congress/ptrs", params={"year": 2026}, headers=DEMO)
    assert r.status_code == 502 and r.json()["detail"] == {"code": "provider_error",
                                                           "message": "A House Clerk respondeu HTTP 500."}


def test_network_error_and_quota(house: tuple[TestClient, House], monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import congress, providers
    c, _ = house

    def down(url: str) -> httpx.Response:
        raise httpx.ConnectError("offline test")

    monkeypatch.setattr(congress, "_http_get", down)
    r = c.get("/api/congress/ptrs", params={"year": 2026}, headers=DEMO)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "provider_unreachable"
    assert "ConnectError" in r.json()["detail"]["message"]
    providers.reset()
    monkeypatch.setattr(congress, "_http_get", House())
    per_minute = providers.PROVIDERS["house_clerk"].per_minute
    for _ in range(per_minute):
        providers.acquire("house_clerk")
    r = c.get("/api/congress/ptrs", params={"year": 2026}, headers=DEMO)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "rate_limited"


# ---------------------------------------------------------------- one PTR

@pytest.mark.parametrize("doc_id,filed", [("20035143", "2026-08-21"), ("20035590", "2026-10-07"),
                                          ("20035562", "2026-10-07"), ("20033725", "2026-01-23")])
def test_report_rows_equal_parse_ptr_text(house: tuple[TestClient, House], doc_id: str, filed: str) -> None:
    c, h = house
    r = c.get(f"/api/congress/ptrs/{doc_id}", params={"year": 2026, "filed": filed}, headers=DEMO)
    assert r.status_code == 200, r.text
    d = r.json()
    oracle = engine().parse_ptr_text((FIX / TEXTS[doc_id]).read_text(encoding="utf-8"), filed)
    assert d["rows"] == oracle["rows"] and d["rows"]
    assert (d["name"], d["status"], d["district"], d["filed"]) == (oracle["name"], oracle["status"],
                                                                    oracle["district"], oracle["filed"])
    assert d["readable"] is True and d["note"] is None and d["from_cache"] is False
    assert d["pdf_url"] == PTR_URL % doc_id and h.calls == [PTR_URL % doc_id]
    assert d["senate"]["covered"] is False and "collected_at" in d and "date = data da operação" in d["dates_note"]
    for row in d["rows"]:                                    # trade date and disclosure delay, never mixed
        assert row["date"] <= filed and row["days_to_disclose"] >= 0 and isinstance(row["late"], bool)


def test_report_known_values_and_late_flag(house: tuple[TestClient, House]) -> None:
    c, _ = house
    d = c.get("/api/congress/ptrs/20035143", params={"year": 2026, "filed": "2026-08-21"}, headers=DEMO).json()
    calls = [x for x in d["rows"] if x["ticker"] == "BE" and x["asset_type"] == "OP"]
    assert calls[0]["amount"] == "$1,000,001 - $5,000,000" and calls[0]["date"] == "2026-07-24"
    assert calls[0]["days_to_disclose"] == 28 and calls[0]["late"] is False and calls[0]["owner_name"] == "spouse"
    # without `filed`, the date comes from the signature in the document, as the engine reads it
    d = c.get("/api/congress/ptrs/20035143", params={"year": 2026}, headers=DEMO).json()
    assert d["filed"] == "2026-08-21" and d["from_cache"] is True
    # a later document date makes every row late (> 45 days), from the engine's rule
    d = c.get("/api/congress/ptrs/20035590", params={"year": 2026, "filed": "2026-11-15"}, headers=DEMO).json()
    assert d["rows"] and all(x["late"] for x in d["rows"])


def test_pdf_cached_for_good(house: tuple[TestClient, House], settings_env: Path) -> None:
    c, h = house
    a = c.get("/api/congress/ptrs/20035143", params={"year": 2026}, headers=DEMO).json()
    b = c.get("/api/congress/ptrs/20035143", params={"year": 2026}, headers=DEMO).json()
    assert h.calls == [PTR_URL % "20035143"] and b["from_cache"] is True and a["collected_at"] == b["collected_at"]
    assert (settings_env / "data" / "cache" / "house_clerk" / "2026-20035143.pdf").read_bytes() == fake_pdf("20035143")


def test_unreadable_without_pdftotext(house: tuple[TestClient, House], monkeypatch: pytest.MonkeyPatch) -> None:
    """The real `_pdf_text` (the engine's pdf_to_text) with no pdftotext on the PATH: the filing, its dates and
    the link, without rows and with a plain note."""
    import shutil

    from app.services import congress
    c, _ = house
    monkeypatch.setattr(congress, "_pdf_text", lambda p: engine().pdf_to_text(str(p)))
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: None)
    d = c.get("/api/congress/ptrs/20035143", params={"year": 2026, "filed": "2026-08-21"}, headers=DEMO).json()
    assert d["readable"] is False and d["rows"] is None and "pdftotext" in d["note"]
    assert d["filed"] == "2026-08-21" and d["pdf_url"] == PTR_URL % "20035143" and "collected_at" in d


def test_no_rows_recognised(house: tuple[TestClient, House], monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import congress
    c, _ = house
    monkeypatch.setattr(congress, "_pdf_text", lambda p: "Name: Hon. Test\nnothing that looks like a trade\n")
    d = c.get("/api/congress/ptrs/20035143", params={"year": 2026}, headers=DEMO).json()
    assert d["readable"] is True and d["rows"] == [] and "Nenhuma linha" in d["note"]


def test_report_errors(house: tuple[TestClient, House], settings_env: Path) -> None:
    c, h = house
    for bad in ("abc", "12a4", "1234567890123", "..%2Fsecret"):
        r = c.get(f"/api/congress/ptrs/{bad}", params={"year": 2026}, headers=DEMO)
        assert r.status_code in (400, 404), bad
        if r.status_code == 400:
            assert r.json()["detail"]["code"] == "invalid_doc_id"
    assert h.calls == []                                          # nothing downloaded for an invalid DocID
    r = c.get("/api/congress/ptrs/99999999", params={"year": 2026}, headers=DEMO)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "not_found"
    url = PTR_URL % "20035143"
    h.override[url] = httpx.Response(200, content=b"<html>maintenance</html>", request=httpx.Request("GET", url))
    r = c.get("/api/congress/ptrs/20035143", params={"year": 2026}, headers=DEMO)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "bad_payload"
    assert not (settings_env / "data" / "cache" / "house_clerk" / "2026-20035143.pdf").exists()


def test_concurrent_requests_download_once(house: tuple[TestClient, House], monkeypatch: pytest.MonkeyPatch) -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from app.services import congress
    c, h = house
    gate = threading.Event()

    def slow(url: str) -> httpx.Response:
        gate.wait(5)
        return h(url)

    monkeypatch.setattr(congress, "_http_get", slow)
    with ThreadPoolExecutor(4) as pool:
        futs = [pool.submit(congress._download, INDEX_URL) for _ in range(4)]
        threading.Timer(0.3, gate.set).start()
        results = [f.result(timeout=10) for f in futs]
    assert all(r == ZIP.read_bytes() for r in results)
    assert h.calls == [INDEX_URL]


# ---------------------------------------------------------------- display policy

@pytest.fixture()
def public(settings_env: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, House, Path]]:
    from .test_public import _demo_db
    ws = _demo_db(settings_env, monkeypatch)
    monkeypatch.setenv("DP_AUTH_MODE", "public")
    monkeypatch.setenv("DP_PUBLIC_WORKSPACE_ID", str(ws))
    monkeypatch.setenv("DP_RATE_LIMIT_PER_MIN", "10000")
    monkeypatch.delenv("DP_PELOSI_PUBLIC", raising=False)
    _reset()
    from app.services.public_lab import setup_public_lab
    setup_public_lab(ws)
    from app.main import create_app
    from app.services import congress
    h = House()
    monkeypatch.setattr(congress, "_http_get", h)
    monkeypatch.setattr(congress, "_pdf_text", text_for)
    with TestClient(create_app(), client=("198.51.100.7", 4000)) as c:
        yield c, h, settings_env
    _reset()


def test_public_lab_off_by_default(public: tuple[TestClient, House, Path]) -> None:
    c, h, root = public
    for path in ("/api/congress/ptrs?year=2026", "/api/congress/ptrs/20035143?year=2026"):
        r = c.get(path)
        assert r.status_code == 403 and r.json()["detail"]["code"] == "display_policy", path
        assert "13107" in r.json()["detail"]["message"]
    assert h.calls == []                                          # refused before any download
    assert not (root / "data" / "cache" / "house_clerk").exists()
    pol = c.get("/api/workspace").json()["display_policy"]
    assert pol["pelosi_public"] is False and pol["pelosi_shown"] is False


def test_public_lab_on_with_the_switch(public: tuple[TestClient, House, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    from app import config
    c, h, _ = public
    monkeypatch.setenv("DP_PELOSI_PUBLIC", "true")
    config.get_settings.cache_clear()
    d = c.get("/api/congress/ptrs", params={"year": 2026, "member": "pelosi"}).json()
    assert _no_collected(d["filings"]) == cli("--member", "pelosi")
    rep = c.get("/api/congress/ptrs/20035143", params={"year": 2026, "filed": "2026-08-21"}).json()
    assert len(rep["rows"]) == 7 and h.calls == [INDEX_URL, PTR_URL % "20035143"]
    pol = c.get("/api/workspace").json()["display_policy"]
    assert pol["pelosi_public"] is True and pol["pelosi_shown"] is True


def test_demo_policy_says_shown(house: tuple[TestClient, House]) -> None:
    c, _ = house
    pol = c.get("/api/workspace", headers=DEMO).json()["display_policy"]
    assert pol["pelosi_public"] is False and pol["pelosi_shown"] is True     # the local demo shows them


def test_health_lists_the_engine_and_quota_is_counted(house: tuple[TestClient, House]) -> None:
    from app.services import providers
    c, _ = house
    assert c.get("/api/health").json()["engines"]["pelosi"] == "ok"
    c.get("/api/congress/ptrs", params={"year": 2026}, headers=DEMO)
    c.get("/api/congress/ptrs", params={"year": 2026}, headers=DEMO)          # cached: no quota spent
    c.get("/api/congress/ptrs/20035143", params={"year": 2026}, headers=DEMO)
    hc = {p["id"]: p for p in providers.status()}["house_clerk"]
    assert (hc["kind"], hc["official"], hc["status_code"]) == ("official", True, "active")
    assert hc["usage"] == {"minute": 2, "per_minute": 6, "today": 2, "per_day": 300}
