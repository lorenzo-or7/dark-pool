"""Job handlers: Market Scanner, Time Machine and backtests. Each one validates,
freezes the data it uses, calls the engine and stores what came back, nothing
more. Failures are recorded on the experiment / scan, never replaced by data."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, update

from ..config import ENGINE_VERSION, get_settings
from ..db import (data_snapshots, experiments, now, scan_runs, simulated_trades, simulation_runs, strategies,
                  strategy_versions, tx, watchlist_assets)
from ..engines.runner import last_error_line, run_script
from . import market_data as md
from .backtest import DAILY_RULES, BacktestError, backtest_daily, backtest_orb
from .jobs import FAILURE_HOOKS, JobContext, JobFailure, handler
from .metrics import summarize

UNIVERSE_FILE = "universe.txt"


def universe_path() -> Path:
    return get_settings().dp_data_dir / "universe" / UNIVERSE_FILE


# ---------------------------------------------------------------- scanner

@handler("scan.universe")
def scan_universe(ctx: JobContext) -> dict:
    ctx.progress(10, "Baixando diretórios da Nasdaq Trader")
    out = universe_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    res = run_script("scanner", ["universe", "--out", str(out)], ctx.workdir, timeout_s=180, cancelled=ctx.cancelled)
    if res.returncode != 0:
        raise JobFailure(last_error_line(res))
    lines = [x for x in res.stdout.splitlines() if x.strip()]
    count = sum(1 for _ in out.open(encoding="utf-8")) if out.exists() else 0
    return {"symbols": count, "report": lines[:4], "path": "universe/universe.txt", "fetched_at": now().isoformat()}


@handler("scan.daily")
def scan_daily(ctx: JobContext) -> dict:
    p = ctx.params
    scan_id = uuid.UUID(p["scan_id"])
    args = ["daily", "--json", "--no-write", "--quiet", "--min-price", str(p["min_price"]),
            "--min-volume", str(int(p["min_volume"])), "--show", "0"]
    if p["source"] == "universe":
        u = universe_path()
        if not u.exists():
            raise JobFailure("A lista de ações ainda não foi baixada. Atualize o universo primeiro.")
        args += ["--universe", str(u), "--limit", str(int(p["limit"]))]
        n = int(p["limit"])
    else:
        syms = p["symbols"]
        if not syms:
            raise JobFailure("Nenhum ticker para analisar.")
        args += ["--symbols", ",".join(syms)]
        n = len(syms)
    with tx(ctx.user.id, ctx.user.email) as conn:
        conn.execute(update(scan_runs).where(scan_runs.c.id == scan_id).values(status="running"))
    ctx.progress(5, f"Buscando fechamentos diários de {n} ativos ({(n + 19) // 20} requisições)")

    def on_line(line: str) -> None:
        if "spark" in line and " of " in line:
            try:
                k, total = (int(x) for x in line.split("spark", 1)[1].split("requests")[0].split(" of "))
                ctx.progress(5 + int(85 * k / max(total, 1)), line.strip())
            except ValueError:
                pass

    res = run_script("scanner", args, ctx.workdir, timeout_s=min(900, 60 + n), cancelled=ctx.cancelled,
                     on_line=on_line)
    if res.returncode not in (0, 1):
        raise JobFailure(last_error_line(res))
    try:
        doc = json.loads(res.stdout)
    except ValueError:
        raise JobFailure(last_error_line(res))
    result = {
        "mode": "daily", "as_of": doc.get("as_of"), "universe": doc.get("universe"), "scanned": doc.get("scanned"),
        "failed": doc.get("failed"), "filters": doc.get("filters"), "hits": doc.get("hits", []),
        "source": md.SOURCE_LABEL, "note": doc.get("note"), "engine": ENGINE_VERSION,
        "partial": bool(doc.get("failed")),
        "criteria": {
            "breakout_20d": "Último fechamento acima de todos os fechamentos das 20 sessões anteriores.",
            "bull_flag": "Alta de mais de 10% nas 10 sessões antes das 5 últimas; 5 últimos fechamentos numa faixa de 5%.",
            "reclaim_ma20": "Fechamento anterior abaixo da média de 20 dias e último fechamento acima dela.",
            "oversold": "RSI 14 (Wilder) abaixo de 30.",
            "oversold_bounce": "RSI 14 abaixo de 30 ontem e fechamento de hoje em alta.",
        },
    }
    with tx(ctx.user.id, ctx.user.email) as conn:
        conn.execute(update(scan_runs).where(scan_runs.c.id == scan_id).values(status="succeeded", result=result))
    return {"scan_id": str(scan_id), "hits": len(result["hits"]), "scanned": result["scanned"]}


def _scan_failed(ctx: JobContext, message: str, status: str) -> None:
    sid = ctx.params.get("scan_id")
    if sid:
        with tx(ctx.user.id, ctx.user.email) as conn:
            conn.execute(update(scan_runs).where(scan_runs.c.id == uuid.UUID(sid)).values(status=status, error=message))


FAILURE_HOOKS["scan.daily"] = _scan_failed


def watchlist_symbols(conn, workspace_id: uuid.UUID, watchlist_id: uuid.UUID) -> list[str]:  # noqa: ANN001
    return [r.symbol for r in conn.execute(select(watchlist_assets.c.symbol).where(
        watchlist_assets.c.workspace_id == workspace_id, watchlist_assets.c.watchlist_id == watchlist_id))]


# ---------------------------------------------------------------- snapshots

def _snapshot_for(ctx: JobContext, symbol: str, snapshot_id: str | None, rng: str, interval: str) -> tuple[dict, str]:
    """A frozen snapshot row and its text: the one asked for, or a fresh download frozen now."""
    if snapshot_id:
        with tx(ctx.user.id, ctx.user.email) as conn:
            row = conn.execute(select(data_snapshots).where(data_snapshots.c.id == uuid.UUID(snapshot_id),
                                                            data_snapshots.c.workspace_id == ctx.user.workspace_id)
                               ).mappings().first()
        if row is None:
            raise JobFailure("Snapshot não encontrado neste workspace.")
        if row["symbol"] != symbol:
            raise JobFailure(f"O snapshot é de {row['symbol']}, não de {symbol}.")
        if row["interval"] != interval:
            raise JobFailure(f"O snapshot tem candles de {row['interval']}; esta análise precisa de {interval}.")
        try:
            return dict(row), md.read_snapshot_text(row["sha256"])
        except md.DataError as e:
            raise JobFailure(e.message)
    ctx.progress(10, f"Baixando {rng} de candles de {interval} de {symbol}")
    try:
        text, fetched, _ = md.fetch_chart_raw(symbol, rng, interval, use_cache=False)
    except md.DataError as e:
        raise JobFailure(e.message, e.code)
    with tx(ctx.user.id, ctx.user.email) as conn:
        row = md.freeze_snapshot(conn, ctx.user.workspace_id, ctx.user.id, text, symbol, interval, rng, md.SOURCE,
                                 fetched)
    return row, text


def _set_experiment(ctx: JobContext, exp_id: uuid.UUID, **values: object) -> None:
    with tx(ctx.user.id, ctx.user.email) as conn:
        conn.execute(update(experiments).where(experiments.c.id == exp_id).values(updated_at=now(), **values))


def _experiment_failed(ctx: JobContext, message: str, status: str) -> None:
    eid = ctx.params.get("experiment_id")
    if eid:
        _set_experiment(ctx, uuid.UUID(eid), status=status, error=message)


def _store_trades(conn, ctx: JobContext, exp_id: uuid.UUID, symbol: str, source: str, trades: list[dict]) -> None:  # noqa: ANN001
    if not trades:
        return
    conn.execute(simulated_trades.insert(), [{
        "id": uuid.uuid4(), "workspace_id": ctx.user.workspace_id, "experiment_id": exp_id, "source": source,
        "dataset": t.get("dataset", "full"), "symbol": symbol, "entry_date": t["entry_date"],
        "entry_time": t.get("entry_time"), "entry": t["entry"], "stop": t["stop"], "target": t.get("target"),
        "exit_price": t.get("exit_price"), "exit_date": t.get("exit_date"), "outcome": t["outcome"],
        "r_multiple": t["r_multiple"], "created_at": now(),
    } for t in trades])


# ---------------------------------------------------------------- time machine

def _ampm(hhmm: str) -> str:
    h, m = map(int, hhmm.split(":"))
    return f"{h % 12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


@handler("timemachine.run")
def timemachine_run(ctx: JobContext) -> dict:
    p = ctx.params
    exp_id = uuid.UUID(p["experiment_id"])
    _set_experiment(ctx, exp_id, status="running")
    snap, text = _snapshot_for(ctx, p["symbol"], p.get("snapshot_id"), "60d", "5m")
    _set_experiment(ctx, exp_id, data_snapshot_id=snap["id"])
    ctx.workdir.mkdir(parents=True, exist_ok=True)
    data_file = ctx.workdir / "chart.json"
    data_file.write_text(text, encoding="utf-8")
    out_file = ctx.workdir / "timemachine.json"
    args = ["run", "--offline", str(data_file), "--symbol", p["symbol"], "--date", p["date"],
            "--entry", repr(float(p["entry"])), "--stop", repr(float(p["stop"])), "--target", repr(float(p["target"])),
            "--entry-time", _ampm(p["entry_time"]), "--replays", str(int(p["replays"])), "--seed", str(int(p["seed"])),
            "--window", str(int(p["window"])), "--or-minutes", str(int(p["or_minutes"])),
            "--write", str(out_file), "--json"]
    if p.get("until"):
        args += ["--until", p["until"]]
    ctx.progress(30, f"Executando {int(p['replays']):,} replays (seed {p['seed']})".replace(",", "."))
    res = run_script("timemachine", args, ctx.workdir, timeout_s=300, cancelled=ctx.cancelled)
    if res.returncode != 0 or not out_file.exists():
        raise JobFailure(last_error_line(res))
    doc = json.loads(out_file.read_text(encoding="utf-8"))
    mc, hist = doc["mc"], doc.get("history") or {}
    ctx.progress(90, "Gravando resultados")
    trades = [{"entry_date": t["date"], "entry_time": t["time"], "entry": t["entry"], "stop": t["stop"],
               "target": t["target"], "exit_price": None, "exit_date": t["date"], "outcome": t["outcome"],
               "r_multiple": t["R"], "dataset": "full"} for t in hist.get("trades", [])]
    results = {
        "plan": doc["plan"], "mc": mc, "history": {k: v for k, v in hist.items() if k != "trades"},
        "verdict": doc.get("verdict"), "verdict_notes": doc.get("verdict_notes") or [],
        "warnings": doc.get("warnings") or [], "note": doc.get("note"), "data": doc.get("data"),
        "history_summary": summarize(trades),
        "snapshot": {"id": str(snap["id"]), "sha256": snap["sha256"], "source": snap["source"],
                     "fetched_at": _iso(snap["fetched_at"]), "is_fixture": bool(snap.get("is_fixture"))},
        "algorithm_version": ENGINE_VERSION + " / timemachine",
        "limitations": [
            "Simulação construída a partir das sessões recentes do próprio ativo. Não é previsão.",
            "Os candles de 5 min são sorteados um a um, sem dependência entre eles: tendência e mudanças de volatilidade do dia não são modeladas.",
            "Gap através do stop conta como -1R; um candle que toca stop e alvo conta como stop. Sem custos nem slippage.",
            "Eventos ausentes da janela (resultados, notícias, suspensões) não aparecem nas simulações.",
        ],
    }
    with tx(ctx.user.id, ctx.user.email) as conn:
        conn.execute(simulation_runs.insert().values(
            id=uuid.uuid4(), workspace_id=ctx.user.workspace_id, experiment_id=exp_id, symbol=p["symbol"],
            plan=doc["plan"], seed=int(p["seed"]), replays=int(p["replays"]), algorithm_version=results["algorithm_version"],
            data_source=snap["source"], data_snapshot_id=snap["id"], snapshot_sha256=snap["sha256"],
            pool_from=mc.get("pool_from"), pool_to=mc.get("pool_to"), pool_sessions=mc.get("pool_sessions"),
            results={"mc": {k: v for k, v in mc.items() if k not in ("sample_paths",)}}, created_by=ctx.user.id,
            created_at=now()))
        _store_trades(conn, ctx, exp_id, p["symbol"], "timemachine_history", trades)
        conn.execute(update(experiments).where(experiments.c.id == exp_id).values(
            status="succeeded", results=results, updated_at=now()))
    return {"experiment_id": str(exp_id), "p_target": mc["p_target"], "p_stop": mc["p_stop"]}


FAILURE_HOOKS["timemachine.run"] = _experiment_failed


def _iso(d) -> str | None:  # noqa: ANN001
    if d is None:
        return None
    if isinstance(d, str):
        return d
    return (d if d.tzinfo else d.replace(tzinfo=UTC)).isoformat()


# ---------------------------------------------------------------- backtests

@handler("backtest.run")
def backtest_run(ctx: JobContext) -> dict:
    p = ctx.params
    exp_id = uuid.UUID(p["experiment_id"])
    _set_experiment(ctx, exp_id, status="running")
    cfg = p["config"]
    symbol = cfg["symbol"]
    rule = cfg["rule"]["type"]
    split = p.get("split_date")
    if rule == "orb":
        snap, text = _snapshot_for(ctx, symbol, p.get("snapshot_id"), "60d", "5m")
        ctx.progress(50, "Reexecutando a regra ORB em cada sessão")
        try:
            out = backtest_orb(text, symbol, cfg, split)
        except BacktestError as e:
            raise JobFailure(str(e))
    elif rule in DAILY_RULES:
        snap, text = _snapshot_for(ctx, symbol, p.get("snapshot_id"), p.get("range", "2y"), "1d")
        ctx.progress(50, "Calculando sinais sem informação futura")
        try:
            out = backtest_daily(md.parse_chart(text, symbol), cfg, split, cancelled=ctx.cancelled)
        except BacktestError as e:
            raise JobFailure(str(e))
    else:
        raise JobFailure(f"Regra sem motor de backtest: {rule}")
    _set_experiment(ctx, exp_id, data_snapshot_id=snap["id"])
    trades = out.pop("trades")
    summary = {"all": summarize(trades)}
    if split:
        summary["development"] = summarize([t for t in trades if t["dataset"] == "development"])
        summary["out_of_sample"] = summarize([t for t in trades if t["dataset"] == "out_of_sample"])
    results = {**out, "summary": summary, "config": cfg, "algorithm_version": "darkpool-backtest 0.1 / " + ENGINE_VERSION,
               "snapshot": {"id": str(snap["id"]), "sha256": snap["sha256"], "source": snap["source"],
                            "fetched_at": _iso(snap["fetched_at"]), "is_fixture": bool(snap.get("is_fixture"))}}
    with tx(ctx.user.id, ctx.user.email) as conn:
        _store_trades(conn, ctx, exp_id, symbol, "backtest", trades)
        conn.execute(update(experiments).where(experiments.c.id == exp_id).values(
            status="succeeded", results=results, updated_at=now()))
    return {"experiment_id": str(exp_id), "trades": len(trades)}


FAILURE_HOOKS["backtest.run"] = _experiment_failed


def strategy_config(conn, workspace_id: uuid.UUID, strategy_id: uuid.UUID, version: int | None) -> tuple[dict, int, str]:  # noqa: ANN001
    s = conn.execute(select(strategies).where(strategies.c.id == strategy_id,
                                              strategies.c.workspace_id == workspace_id)).mappings().first()
    if s is None:
        raise LookupError("strategy")
    v = version or s["current_version"]
    row = conn.execute(select(strategy_versions.c.config).where(strategy_versions.c.strategy_id == strategy_id,
                                                                strategy_versions.c.version == v)).first()
    if row is None:
        raise LookupError("version")
    return row.config, v, s["name"]


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()
