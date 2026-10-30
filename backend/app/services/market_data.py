"""Market data adapter. Every price in DARK POOL comes through here, so the
provider can be swapped later. Today: Yahoo Finance chart API (free,
unofficial, delayed). Responses are cached on disk and frozen as snapshots
when an experiment needs to be reproducible."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import Connection, select

from ..config import get_settings
from ..db import data_snapshots, new_id, now

SOURCE = "yahoo"
SOURCE_LABEL = "Yahoo Finance (API não oficial, cotações com atraso)"
UA = "Mozilla/5.0 (compatible; DARK-POOL/0.1; research lab)"
HOSTS = ("https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com")
SYMBOL_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")
ALLOWED = {
    ("1d", "5m"), ("5d", "5m"), ("60d", "5m"),
    ("1mo", "1d"), ("3mo", "1d"), ("6mo", "1d"), ("1y", "1d"), ("2y", "1d"), ("5y", "1d"), ("5y", "1wk"),
}
TTL = {"5m": 120, "1d": 1800, "1wk": 6 * 3600}
_lock = threading.Lock()
_last_call = 0.0


class DataError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def clean_symbol(sym: str) -> str:
    s = (sym or "").strip().upper()
    if not SYMBOL_RE.match(s):
        raise DataError("invalid_symbol", f"Ticker inválido: {sym!r}. Use de 1 a 5 letras (ex.: TSLA, BRK.B).")
    return s


def _cache_dir() -> Path:
    d = get_settings().dp_data_dir / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _polite() -> None:
    global _last_call
    with _lock:
        wait = 0.3 - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def fetch_chart_raw(symbol: str, rng: str, interval: str, use_cache: bool = True) -> tuple[str, datetime, bool]:
    """-> (raw JSON text, fetched_at UTC, from_cache)."""
    symbol = clean_symbol(symbol)
    if (rng, interval) not in ALLOWED:
        raise DataError("invalid_range", f"Combinação de período/intervalo não suportada: {rng}/{interval}")
    cache = _cache_dir() / f"{symbol}-{rng}-{interval}.json"
    if use_cache and cache.exists() and time.time() - cache.stat().st_mtime < TTL[interval]:
        return cache.read_text(encoding="utf-8"), datetime.fromtimestamp(cache.stat().st_mtime, UTC), True
    ysym = symbol.replace(".", "-")
    last_status: int | None = None
    for host in HOSTS:
        for attempt in (0, 1):
            _polite()
            url = f"{host}/v8/finance/chart/{ysym}"
            try:
                r = httpx.get(url, params={"range": rng, "interval": interval, "includePrePost": "false"},
                              headers={"User-Agent": UA, "Accept": "application/json"}, timeout=20)
            except httpx.TimeoutException:
                raise DataError("provider_timeout", "O provedor de dados não respondeu a tempo.")
            except httpx.HTTPError as e:
                raise DataError("provider_unreachable", f"Não foi possível acessar o provedor de dados: {e}")
            last_status = r.status_code
            if r.status_code == 200:
                cache.write_text(r.text, encoding="utf-8")
                return r.text, now(), False
            if r.status_code == 404:
                raise DataError("unknown_symbol", f"O provedor não tem dados para {symbol}.")
            if r.status_code == 429 and attempt == 0:
                time.sleep(5)
                continue
            break
    if last_status == 429:
        raise DataError("rate_limited", "O provedor está limitando requisições (HTTP 429). Tente em um minuto.")
    raise DataError("provider_error", f"O provedor respondeu HTTP {last_status}.")


@dataclass
class Chart:
    symbol: str
    meta: dict
    bars: list[dict]


def parse_chart(text: str, symbol: str) -> Chart:
    try:
        data = json.loads(text)
        res = data["chart"]["result"]
    except (ValueError, KeyError, TypeError):
        raise DataError("bad_payload", "O provedor devolveu um formato inesperado.")
    if not res:
        err = (data.get("chart") or {}).get("error") or {}
        raise DataError("unknown_symbol", err.get("description") or f"Sem dados para {symbol}.")
    r0 = res[0]
    meta = r0.get("meta") or {}
    ts = r0.get("timestamp") or []
    q = ((r0.get("indicators") or {}).get("quote") or [{}])[0] or {}
    bars = []
    for i, t in enumerate(ts):
        o, h, lo, c = (q.get(k, [None] * len(ts))[i] for k in ("open", "high", "low", "close"))
        v = (q.get("volume") or [None] * len(ts))[i]
        if t is None or None in (o, h, lo, c):
            continue
        bars.append({"time": int(t), "open": round(o, 4), "high": round(h, 4), "low": round(lo, 4),
                     "close": round(c, 4), "volume": int(v or 0)})
    return Chart(symbol=symbol, meta=meta, bars=bars)


def provenance(chart: Chart, fetched_at: datetime, from_cache: bool, interval: str) -> dict:
    m = chart.meta
    last_bar = chart.bars[-1]["time"] if chart.bars else None
    rmt = m.get("regularMarketTime")
    return {
        "source": SOURCE,
        "source_label": SOURCE_LABEL,
        "fetched_at": fetched_at.isoformat(),
        "from_cache": from_cache,
        "interval": interval,
        "last_bar_time": datetime.fromtimestamp(last_bar, UTC).isoformat() if last_bar else None,
        "market_time": datetime.fromtimestamp(rmt, UTC).isoformat() if rmt else None,
        "exchange": m.get("fullExchangeName") or m.get("exchangeName"),
        "currency": m.get("currency"),
        "timezone": m.get("exchangeTimezoneName") or "America/New_York",
        "delayed": True,
        "note": "Dados gratuitos com atraso. Não são cotações em tempo real.",
    }


# ---------------------------------------------------------------- snapshots

def snapshot_dir() -> Path:
    d = get_settings().dp_data_dir / "snapshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def snapshot_file(sha: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise DataError("bad_snapshot", "Hash de snapshot inválido.")
    return snapshot_dir() / f"{sha}.json.gz"


def freeze_snapshot(conn: Connection, workspace_id: uuid.UUID, user_id: uuid.UUID | None, text: str, symbol: str,
                    interval: str, rng: str, source: str, fetched_at: datetime, is_fixture: bool = False) -> dict:
    """Store the exact payload once (content-addressed) and record it. Returns the snapshot row."""
    sha = sha256_text(text)
    existing = conn.execute(select(data_snapshots).where(data_snapshots.c.workspace_id == workspace_id,
                                                         data_snapshots.c.sha256 == sha)).mappings().first()
    path = snapshot_file(sha)
    if not path.exists():
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write(text)
    # The local file is only a cache on a host with an ephemeral disk: the durable copy goes to
    # the private snapshots bucket, under the workspace's own prefix.
    _persist(workspace_id, sha, path)
    if existing:
        return dict(existing)
    chart = parse_chart(text, symbol)
    row = {
        "id": new_id(), "workspace_id": workspace_id, "symbol": symbol, "interval": interval, "range": rng,
        "source": source, "sha256": sha, "storage_path": path.name, "bars": len(chart.bars),
        "first_bar": datetime.fromtimestamp(chart.bars[0]["time"], UTC) if chart.bars else None,
        "last_bar": datetime.fromtimestamp(chart.bars[-1]["time"], UTC) if chart.bars else None,
        "fetched_at": fetched_at, "is_fixture": is_fixture, "created_by": user_id, "created_at": now(),
    }
    conn.execute(data_snapshots.insert().values(**row))
    return row


def _persist(workspace_id: uuid.UUID, sha: str, path: Path) -> None:
    from . import storage
    if storage.backend() == "local":
        return
    key = storage.object_key(workspace_id, f"{sha}.json.gz")
    try:
        storage.put(storage.BUCKET_SNAPSHOTS, key, path.read_bytes(), "application/gzip", workspace_id)
    except storage.StorageError as e:
        raise DataError("snapshot_storage", f"Não foi possível guardar o snapshot: {e}")


def _verified(raw_gz: bytes, sha: str) -> str:
    text = gzip.decompress(raw_gz).decode("utf-8")
    if sha256_text(text) != sha:
        raise DataError("snapshot_corrupt", "O snapshot não confere com o hash registrado.")
    return text


def read_snapshot_text(sha: str, workspace_id: uuid.UUID | None = None) -> str:
    """The frozen payload, checked against its hash. Order: local cache, the workspace's private
    bucket (after a restart the cache is empty), then the skill's bundled reference file."""
    path = snapshot_file(sha)
    if path.exists():
        return _verified(path.read_bytes(), sha)
    if workspace_id is not None:
        from . import storage
        if storage.backend() != "local":
            try:
                raw = storage.get(storage.BUCKET_SNAPSHOTS, storage.object_key(workspace_id, f"{sha}.json.gz"),
                                  workspace_id)
            except storage.StorageError as e:
                raise DataError("snapshot_storage", f"Não foi possível ler o snapshot: {e}")
            if raw is not None:
                text = _verified(raw, sha)
                path.write_bytes(raw)
                return text
    fx = fixture_path()
    if fx.exists():
        raw = fx.read_bytes()
        if sha256_text(gzip.decompress(raw).decode("utf-8")) == sha:
            path.write_bytes(raw)
            return _verified(raw, sha)
    raise DataError("snapshot_missing", "O arquivo do snapshot não foi encontrado no armazenamento.")


def fixture_path() -> Path:
    return get_settings().dp_skill_dir / "tests" / "fixtures" / "trader-timemachine" / "TSLA-60d5m.json.gz"


def register_fixture(conn: Connection, workspace_id: uuid.UUID, user_id: uuid.UUID | None) -> dict | None:
    """The skill's saved TSLA file (60 days of 5-min bars up to Oct 2026), used for the regression run."""
    p = fixture_path()
    if not p.exists():
        return None
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        text = fh.read()
    # The file was saved by the skill's author right after its last bar; the file's own mtime is only
    # when it was unpacked here, so the last bar is the honest "data as of" time.
    bars = parse_chart(text, "TSLA").bars
    fetched = datetime.fromtimestamp(bars[-1]["time"], UTC) if bars else datetime.fromtimestamp(p.stat().st_mtime, UTC)
    return freeze_snapshot(conn, workspace_id, user_id, text, "TSLA", "5m", "60d",
                           "fixture:day-trader-skill/TSLA-60d5m", fetched, is_fixture=True)
