"""Market Scanner: universe, asset search, charts with indicators, quotes,
news and fundamentals, scans and watchlists."""

from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import delete, desc, func, select, update

from ..auth import CurrentUser, current_user
from ..config import get_settings
from ..db import new_id, now, scan_runs, tx, watchlist_assets, watchlists
from ..engines.runner import EngineTimeout, last_error_line, run_script
from ..schemas import ScanRequest, WatchlistAssetAdd, WatchlistCreate
from ..services import indicators as ind
from ..services import jobs as jobsvc
from ..services import market_data as md
from ..services.tasks import universe_path, watchlist_symbols
from .common import audit, bad_request, not_found, rows, ser

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


def _err(e: md.DataError) -> JSONResponse:
    code = {"invalid_symbol": 400, "invalid_range": 400, "unknown_symbol": 404, "rate_limited": 429}.get(e.code, 502)
    return JSONResponse({"detail": {"code": e.code, "message": e.message}}, status_code=code)


# ---------------------------------------------------------------- universe and search

def _universe() -> list[tuple[str, str]]:
    p = universe_path()
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if "|" in line:
            s, n = line.split("|", 1)
            out.append((s.strip(), n.strip()))
    return out


@router.get("/universe")
def universe_status() -> dict:
    p = universe_path()
    return {"loaded": p.exists(), "symbols": len(_universe()) if p.exists() else 0,
            "updated_at": ser(md.datetime.fromtimestamp(p.stat().st_mtime, md.UTC)) if p.exists() else None,
            "source": "Nasdaq Trader SymDir (nasdaqlisted.txt, otherlisted.txt)"}


@router.post("/universe/refresh", status_code=202)
def universe_refresh(user: CurrentUser = Depends(current_user)) -> dict:
    job, created = jobsvc.submit(user, "scan.universe", {})
    return {"job": ser(job), "created": created}


@router.get("/assets/search")
def search_assets(q: str = Query(min_length=1, max_length=40), limit: int = Query(20, ge=1, le=50)) -> dict:
    u = _universe()
    if not u:
        return {"loaded": False, "results": []}
    qq = q.strip().upper()
    exact = [x for x in u if x[0] == qq]
    prefix = [x for x in u if x[0].startswith(qq) and x[0] != qq]
    name = [x for x in u if qq in x[1].upper() and not x[0].startswith(qq)]
    res = (exact + prefix + name)[:limit]
    return {"loaded": True, "results": [{"symbol": s, "name": n} for s, n in res]}


@router.get("/assets/{symbol}/chart")
def asset_chart(symbol: str, range: Literal["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y"] = "6mo"):  # noqa: A002
    interval = "5m" if range in ("1d", "5d") else "1wk" if range == "5y" else "1d"
    try:
        text, fetched, cached = md.fetch_chart_raw(symbol, range, interval)
        chart = md.parse_chart(text, md.clean_symbol(symbol))
    except md.DataError as e:
        return _err(e)
    closes = [b["close"] for b in chart.bars]
    highs, lows = [b["high"] for b in chart.bars], [b["low"] for b in chart.bars]
    macd_l, macd_s, macd_h = ind.macd(closes)
    meta = chart.meta
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    last = meta.get("regularMarketPrice") or (closes[-1] if closes else None)
    return {
        "symbol": chart.symbol, "name": meta.get("longName") or meta.get("shortName"),
        "range": range, "interval": interval, "bars": chart.bars,
        "indicators": {
            "sma20": [ind.r4(x) for x in ind.sma(closes, 20)], "sma50": [ind.r4(x) for x in ind.sma(closes, 50)],
            "rsi14": [ind.r4(x) for x in ind.rsi(closes, 14)],
            "macd": [ind.r4(x) for x in macd_l], "macd_signal": [ind.r4(x) for x in macd_s],
            "macd_hist": [ind.r4(x) for x in macd_h], "atr14": [ind.r4(x) for x in ind.atr(highs, lows, closes, 14)],
        },
        "quote": {"last": last, "previous_close": prev,
                  "change_pct": round((last / prev - 1) * 100, 3) if last and prev else None,
                  "day_high": meta.get("regularMarketDayHigh"), "day_low": meta.get("regularMarketDayLow"),
                  "volume": meta.get("regularMarketVolume"), "52w_high": meta.get("fiftyTwoWeekHigh"),
                  "52w_low": meta.get("fiftyTwoWeekLow")},
        "provenance": md.provenance(chart, fetched, cached, interval),
        "warnings": ([] if len(chart.bars) >= 20 else ["Poucos candles: indicadores incompletos."]),
    }


@router.get("/quotes")
def quotes(symbols: str = Query(min_length=1, max_length=400)) -> dict:
    syms = []
    for s in symbols.split(","):
        if s.strip():
            try:
                c = md.clean_symbol(s)
            except md.DataError as e:
                raise bad_request(e.message, e.code)
            if c not in syms:
                syms.append(c)
    if len(syms) > 30:
        raise bad_request("No máximo 30 tickers por consulta.")
    out, errors = [], []
    for s in syms:
        try:
            text, fetched, cached = md.fetch_chart_raw(s, "1mo", "1d")
            ch = md.parse_chart(text, s)
        except md.DataError as e:
            errors.append({"symbol": s, "code": e.code, "message": e.message})
            continue
        closes = [b["close"] for b in ch.bars]
        last = ch.meta.get("regularMarketPrice") or (closes[-1] if closes else None)
        prev = closes[-2] if len(closes) >= 2 else None
        vol = [b["volume"] for b in ch.bars]
        rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
        mean = sum(rets) / len(rets) if rets else 0
        vol_pct = (sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)) ** 0.5 * 100 if len(rets) > 2 else None
        out.append({"symbol": s, "name": ch.meta.get("shortName") or ch.meta.get("longName"), "last": last,
                    "change_pct": round((closes[-1] / prev - 1) * 100, 3) if prev else None,
                    "volume": vol[-1] if vol else None, "avg_volume": round(sum(vol) / len(vol)) if vol else None,
                    "volatility_pct": round(vol_pct, 3) if vol_pct is not None else None,
                    "spark": closes[-22:], "as_of": md.provenance(ch, fetched, cached, "1d")["last_bar_time"],
                    "fetched_at": fetched.isoformat()})
    return {"quotes": out, "errors": errors, "source": md.SOURCE_LABEL, "delayed": True}


def _engine_json(name: str, args: list[str], env: dict[str, str] | None = None) -> dict:
    with tempfile.TemporaryDirectory(prefix="dp-") as d:
        try:
            res = run_script(name, args, Path(d), timeout_s=45, env_extra=env)
        except EngineTimeout as e:
            return {"ok": False, "code": "timeout", "message": str(e)}
    try:
        return {"ok": True, "doc": json.loads(res.stdout)}
    except ValueError:
        return {"ok": False, "code": "engine_error", "message": last_error_line(res)}


@router.get("/assets/{symbol}/news")
def asset_news(symbol: str):
    try:
        sym = md.clean_symbol(symbol)
    except md.DataError as e:
        return _err(e)
    ua = get_settings().sec_user_agent
    args = ["--tickers", sym, "--json", "--dry-run", "--no-moves", "--all", "--hours", "168",
            "--state", "state.json", "--watchlist", "none.json", "--plan", "none.json", "--portfolio", "none.json"]
    if not ua:
        args.append("--no-sec")
    r = _engine_json("news", args, {"SEC_USER_AGENT": ua} if ua else None)
    if not r["ok"]:
        return JSONResponse({"detail": {"code": r["code"], "message": r["message"]}}, status_code=502)
    return {"symbol": sym, "sec_included": bool(ua), **r["doc"],
            "note": None if ua else "Filings 8-K da SEC desativados: configure SEC_USER_AGENT no backend."}


@router.get("/assets/{symbol}/fundamentals")
def asset_fundamentals(symbol: str):
    try:
        sym = md.clean_symbol(symbol)
    except md.DataError as e:
        return _err(e)
    ua = get_settings().sec_user_agent
    if not ua:
        return JSONResponse({"detail": {"code": "sec_user_agent_missing",
                                        "message": "A SEC exige SEC_USER_AGENT (nome e e-mail) no backend."}},
                            status_code=424)
    r = _engine_json("analyst", [sym, "--json", "--quarters", "6"], {"SEC_USER_AGENT": ua})
    if not r["ok"]:
        return JSONResponse({"detail": {"code": r["code"], "message": r["message"]}}, status_code=502)
    return {"symbol": sym, "source": "SEC EDGAR (XBRL company facts)", **r["doc"]}


# ---------------------------------------------------------------- scans

@router.post("/scans", status_code=status.HTTP_202_ACCEPTED)
def create_scan(body: ScanRequest, user: CurrentUser = Depends(current_user)) -> dict:
    params = body.model_dump(mode="json")
    if body.source == "watchlist":
        if not body.watchlist_id:
            raise bad_request("Escolha uma watchlist.")
        with tx(user.id, user.email) as conn:
            params["symbols"] = watchlist_symbols(conn, user.workspace_id, body.watchlist_id)
        if not params["symbols"]:
            raise bad_request("A watchlist está vazia.")
        params["source"] = "symbols"
    elif body.source == "symbols" and not body.symbols:
        raise bad_request("Informe ao menos um ticker.")
    scan_id = new_id()
    params["scan_id"] = str(scan_id)
    dedupe = {k: v for k, v in params.items() if k != "scan_id"}

    def created(conn, job_id):  # noqa: ANN001, ANN202
        conn.execute(scan_runs.insert().values(id=scan_id, workspace_id=user.workspace_id, mode="daily",
                                               params=dedupe, status="queued", job_id=job_id, created_by=user.id,
                                               created_at=now()))
        audit(conn, user, "create", "scan", scan_id)

    job, was_created = jobsvc.submit(user, "scan.daily", params, on_created=created, dedupe_params=dedupe)
    return {"job": ser(job), "created": was_created, "scan_id": job["params"]["scan_id"]}


@router.get("/scans")
def list_scans(user: CurrentUser = Depends(current_user), limit: int = Query(20, ge=1, le=100)) -> list[dict]:
    with tx(user.id, user.email) as conn:
        return rows(conn.execute(select(scan_runs.c.id, scan_runs.c.mode, scan_runs.c.params, scan_runs.c.status,
                                        scan_runs.c.error, scan_runs.c.job_id, scan_runs.c.created_at,
                                        scan_runs.c.created_by)
                                 .where(scan_runs.c.workspace_id == user.workspace_id)
                                 .order_by(desc(scan_runs.c.created_at)).limit(limit)))


@router.get("/scans/{scan_id}")
def get_scan(scan_id: uuid.UUID, user: CurrentUser = Depends(current_user)) -> dict:
    with tx(user.id, user.email) as conn:
        r = conn.execute(select(scan_runs).where(scan_runs.c.id == scan_id,
                                                 scan_runs.c.workspace_id == user.workspace_id)).mappings().first()
    if r is None:
        raise not_found("Varredura")
    return ser(dict(r))


# ---------------------------------------------------------------- watchlists

@router.get("/watchlists")
def list_watchlists(user: CurrentUser = Depends(current_user)) -> list[dict]:
    with tx(user.id, user.email) as conn:
        wls = rows(conn.execute(select(watchlists).where(watchlists.c.workspace_id == user.workspace_id)
                                .order_by(watchlists.c.created_at)))
        assets = rows(conn.execute(select(watchlist_assets).where(watchlist_assets.c.workspace_id == user.workspace_id)
                                   .order_by(watchlist_assets.c.created_at)))
    for w in wls:
        w["assets"] = [a for a in assets if a["watchlist_id"] == w["id"]]
    return wls


@router.post("/watchlists", status_code=201)
def create_watchlist(body: WatchlistCreate, user: CurrentUser = Depends(current_user)) -> dict:
    wid = new_id()
    with tx(user.id, user.email) as conn:
        conn.execute(watchlists.insert().values(id=wid, workspace_id=user.workspace_id, name=body.name,
                                                created_by=user.id, updated_by=user.id, created_at=now(),
                                                updated_at=now()))
        audit(conn, user, "create", "watchlist", wid)
    return {"id": str(wid), "name": body.name, "assets": []}


@router.delete("/watchlists/{wid}", status_code=204)
def delete_watchlist(wid: uuid.UUID, user: CurrentUser = Depends(current_user)) -> None:
    with tx(user.id, user.email) as conn:
        r = conn.execute(delete(watchlists).where(watchlists.c.id == wid, watchlists.c.workspace_id == user.workspace_id))
        if not r.rowcount:
            raise not_found("Watchlist")
        audit(conn, user, "delete", "watchlist", wid)


@router.post("/watchlists/{wid}/assets", status_code=201)
def add_asset(wid: uuid.UUID, body: WatchlistAssetAdd, user: CurrentUser = Depends(current_user)) -> dict:
    with tx(user.id, user.email) as conn:
        w = conn.execute(select(watchlists.c.id).where(watchlists.c.id == wid,
                                                       watchlists.c.workspace_id == user.workspace_id)).first()
        if w is None:
            raise not_found("Watchlist")
        n = conn.execute(select(func.count()).select_from(watchlist_assets).where(
            watchlist_assets.c.watchlist_id == wid, watchlist_assets.c.symbol == body.symbol)).scalar()
        if n:
            raise bad_request(f"{body.symbol} já está nesta watchlist.", "duplicate")
        aid = new_id()
        conn.execute(watchlist_assets.insert().values(id=aid, workspace_id=user.workspace_id, watchlist_id=wid,
                                                      symbol=body.symbol, note=body.note or None, added_by=user.id,
                                                      created_at=now()))
        conn.execute(update(watchlists).where(watchlists.c.id == wid).values(updated_at=now(), updated_by=user.id))
        audit(conn, user, "add", "watchlist_asset", aid, {"symbol": body.symbol})
    return {"id": str(aid), "symbol": body.symbol}


@router.delete("/watchlists/{wid}/assets/{symbol}", status_code=204)
def remove_asset(wid: uuid.UUID, symbol: str, user: CurrentUser = Depends(current_user)) -> None:
    with tx(user.id, user.email) as conn:
        r = conn.execute(delete(watchlist_assets).where(watchlist_assets.c.watchlist_id == wid,
                                                        watchlist_assets.c.workspace_id == user.workspace_id,
                                                        watchlist_assets.c.symbol == symbol.upper()))
        if not r.rowcount:
            raise not_found("Ativo")
        audit(conn, user, "remove", "watchlist_asset", None, {"symbol": symbol.upper()})
