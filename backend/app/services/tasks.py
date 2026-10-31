"""Job handlers: Market Scanner, Time Machine and backtests. Each one validates,
freezes the data it uses, calls the engine and stores what came back, nothing
more. Failures are recorded on the experiment / scan, never replaced by data."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

from sqlalchemy import select, update

from ..config import ENGINE_VERSION, get_settings
from ..db import (data_snapshots, experiments, now, scan_runs, simulated_trades, simulation_runs, strategies,
                  strategy_versions, tx, watchlist_assets)
from ..engines.runner import last_error_line, load_module, run_script
from . import alpaca, orb_plan
from . import market_calendar as mcal
from . import market_data as md
from . import providers
from .backtest import DAILY_RULES, BacktestError, backtest_daily, backtest_orb
from .jobs import FAILURE_HOOKS, JobContext, JobFailure, handler
from .metrics import summarize

UNIVERSE_FILE = "universe.txt"


def universe_path() -> Path:
    return get_settings().dp_data_dir / "universe" / UNIVERSE_FILE


# ---------------------------------------------------------------- shared quota

def _spend(ctx: JobContext, pid: str, cost: int) -> None:
    try:
        providers.acquire(pid, cost)
    except providers.ProviderUnavailable as e:
        raise JobFailure(e.message, e.code)


# ---------------------------------------------------------------- scanner

@handler("scan.universe")
def scan_universe(ctx: JobContext) -> dict:
    _spend(ctx, "nasdaq_trader", 2)  # nasdaqlisted.txt and otherlisted.txt
    ctx.progress(10, "Baixando diretórios da Nasdaq Trader")
    out = universe_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    res = run_script("scanner", ["universe", "--out", str(out)], ctx.workdir, timeout_s=180, cancelled=ctx.cancelled)
    if res.returncode != 0:
        raise JobFailure(last_error_line(res))
    lines = [x for x in res.stdout.splitlines() if x.strip()]
    count = sum(1 for _ in out.open(encoding="utf-8")) if out.exists() else 0
    return {"symbols": count, "report": lines[:4], "path": "universe/universe.txt", "fetched_at": now().isoformat()}


CRITERIA_DAILY = {
    "breakout_20d": "Último fechamento acima de todos os fechamentos das 20 sessões anteriores.",
    "bull_flag": "Alta de mais de 10% nas 10 sessões antes das 5 últimas; 5 últimos fechamentos numa faixa de 5%.",
    "reclaim_ma20": "Fechamento anterior abaixo da média de 20 dias e último fechamento acima dela.",
    "oversold": "RSI 14 (Wilder) abaixo de 30.",
    "oversold_bounce": "RSI 14 abaixo de 30 ontem e fechamento de hoje em alta.",
}
CRITERIA_ORB = {
    "orb": "Primeiro candle de 5 min depois da faixa de abertura a FECHAR acima da máxima da faixa, até o horário "
           "de corte. Só gráficos com todos os candles de 9:30 ao corte (uma falta é suspensão ou ausência de negócio).",
}


def _scan_symbols(ctx: JobContext, p: dict) -> list[str]:
    """The symbols of a scan, in the engine's own order: the list given, or the first N of the universe
    (read with the scanner's symbols_from_file)."""
    if p["source"] == "universe":
        u = universe_path()
        if not u.exists():
            raise JobFailure("A lista de ações ainda não foi baixada. Atualize o universo primeiro.")
        sc = load_module("scanner")
        out: list[str] = []
        for x in sc.symbols_from_file(str(u)):
            if x not in out:
                out.append(x)
        return out[: int(p["limit"])]
    if not p["symbols"]:
        raise JobFailure("Nenhum ticker para analisar.")
    return list(p["symbols"])


def _orb_clock(p: dict, now_utc: datetime, data_limit: datetime | None) -> tuple[str, str]:
    """(day, HH:MM cut) of an ORB scan, New York time. Default cut: now (live), or 15:30 for a past day;
    never later than the data the provider serves (Alpaca SIP: now minus 16 minutes)."""
    ny = now_utc.astimezone(mcal.NY)
    day = p.get("day") or ny.date().isoformat()
    if p.get("at"):
        cut = p["at"]
    elif day == ny.date().isoformat():
        lim = (data_limit or now_utc).astimezone(mcal.NY)
        m = lim.hour * 60 + lim.minute
        cut = f"{(m - m % 5) // 60:02d}:{(m - m % 5) % 60:02d}"
    else:
        cut = "15:30"
    if data_limit is not None and day == ny.date().isoformat():
        lim = data_limit.astimezone(mcal.NY)
        h, mi = (int(x) for x in cut.split(":"))
        if h * 60 + mi > lim.hour * 60 + lim.minute:
            raise JobFailure(f"O corte {cut} ainda não está disponível: o plano gratuito da Alpaca libera os dados "
                             f"com 15 minutos de atraso (dados até {lim:%H:%M} ET).", "not_available_yet")
    return day, cut


def _alpaca_bundle(ctx: JobContext, symbols: list[str], mode: str, p: dict) -> tuple[Path, dict, tuple[str, str] | None]:
    """Alpaca bars of every symbol -> one offline bundle {SYM: v8 chart} the scanner reads."""
    f = alpaca.feed()
    now_utc = alpaca._now()
    clock = None
    if mode == "daily":
        start, end = alpaca.daily_window(now_utc)
        timeframe, gran, keep = alpaca.TIMEFRAME_1D, "1d", None
        label = f"fechamentos diários de {len(symbols)} ativos"
    else:
        day, cut = _orb_clock(p, now_utc, alpaca.available_until(now_utc))
        d = datetime.strptime(day, "%Y-%m-%d").date()
        try:
            o, c = alpaca._open_close(d)
        except Exception:  # noqa: BLE001
            raise JobFailure(f"A NYSE não abriu em {day}.", "market_closed")
        h, mi = (int(x) for x in cut.split(":"))
        cut_utc = datetime.combine(d, time(h, mi), mcal.NY).astimezone(UTC)
        start, end = o, min(c, cut_utc) - timedelta(seconds=1)
        o_ts, end_ts = int(o.timestamp()), int(end.timestamp())
        timeframe, gran = alpaca.TIMEFRAME_5M, "5m"
        keep = lambda ts: o_ts <= ts <= end_ts  # noqa: E731  (regular session up to the cut)
        clock = (day, cut)
        label = f"candles de 5 min de {len(symbols)} ativos em {day} até {cut} ET"
    est = -(-len(symbols) // alpaca.SCAN_CHUNK)
    ctx.progress(5, f"Baixando {label} (Alpaca, feed {f.upper()})")

    def on_page(n: int) -> None:
        ctx.progress(min(80, 5 + 3 * n), f"Alpaca: {n} página(s) recebida(s) ({est} lote(s) de até {alpaca.SCAN_CHUNK} ativos)")

    try:
        bars, pages = alpaca.fetch_bars_multi(symbols, timeframe, start, end, f, on_page)
    except alpaca.AlpacaError as e:
        raise JobFailure(e.message, e.code)
    bundle = {s: alpaca.scanner_chart(s, rows, f, gran, keep) for s, rows in bars.items() if rows}
    ctx.workdir.mkdir(parents=True, exist_ok=True)
    path = ctx.workdir / "bundle.json"
    path.write_text(json.dumps(bundle, separators=(",", ":")), encoding="utf-8")
    meta = {"provider": alpaca.PROVIDER_ID, "feed": f, "requests": pages, "symbols_with_data": len(bundle),
            "data_end": alpaca._rfc3339(end), "source": alpaca.source(f)}
    return path, meta, clock


def _run_scan(ctx: JobContext) -> dict:
    p = ctx.params
    mode = p.get("mode") or "daily"
    scan_id = uuid.UUID(p["scan_id"])
    symbols = _scan_symbols(ctx, p)
    n = len(symbols)
    with tx(ctx.user.id, ctx.user.email) as conn:
        conn.execute(update(scan_runs).where(scan_runs.c.id == scan_id).values(status="running"))
    ctx.workdir.mkdir(parents=True, exist_ok=True)
    wl = ctx.workdir / "symbols.txt"
    wl.write_text("\n".join(symbols) + "\n", encoding="utf-8")   # a file, not a long command line
    args = [mode, "--json", "--no-write", "--quiet", "--min-price", str(p["min_price"]),
            "--min-volume", str(int(p["min_volume"])), "--show", "0", "--watchlist", str(wl)]
    if mode == "orb":
        args += ["--or-minutes", str(int(p.get("or_minutes") or 15))]
    pid = providers.scan_provider()
    if pid == alpaca.PROVIDER_ID:
        bundle, meta, clock = _alpaca_bundle(ctx, symbols, mode, p)
        args += ["--offline", str(bundle)]
        if mode == "daily":
            args += ["--now", alpaca._rfc3339(alpaca._now())]
        else:
            args += ["--now", f"{clock[0]} {clock[1]}", "--at", clock[1]]
        source_label = f"Alpaca Market Data (feed {meta['feed'].upper()})"
        on_line = None
    else:
        # The scanner reads Yahoo's spark endpoint itself, 20 symbols per request (+ stage-2 charts for orb).
        _spend(ctx, "yahoo", (n + 19) // 20 + (min(n, 200) if mode == "orb" else 0))
        meta = {"provider": "yahoo", "feed": None, "requests": (n + 19) // 20, "source": "yahoo"}
        if mode == "orb":
            day, cut = _orb_clock(p, datetime.now(UTC), None)
            if day != datetime.now(UTC).astimezone(mcal.NY).date().isoformat():
                raise JobFailure("Com o Yahoo a varredura ORB só lê o pregão de hoje: o histórico de 5 min gratuito é "
                                 "curto. Configure a Alpaca para repetir dias anteriores.", "out_of_range")
            if p.get("at"):
                args += ["--at", cut]
        source_label = md.SOURCE_LABEL
        ctx.progress(5, f"Buscando dados de {n} ativos ({(n + 19) // 20} requisições ao Yahoo)")

        def on_line(line: str) -> None:
            if "spark" in line and " of " in line:
                try:
                    k, total = (int(x) for x in line.split("spark", 1)[1].split("requests")[0].split(" of "))
                    ctx.progress(5 + int(85 * k / max(total, 1)), line.strip())
                except ValueError:
                    pass

    ctx.progress(85, "Aplicando as regras do trader-scanner")
    res = run_script("scanner", args, ctx.workdir, timeout_s=min(900, 60 + n), cancelled=ctx.cancelled,
                     on_line=on_line)
    if res.returncode not in (0, 1):
        raise JobFailure(last_error_line(res))
    try:
        doc = json.loads(res.stdout)
    except ValueError:
        raise JobFailure(last_error_line(res))
    result = {
        "mode": mode, "as_of": doc.get("as_of"), "universe": doc.get("universe"), "scanned": doc.get("scanned"),
        "failed": doc.get("failed"), "filters": doc.get("filters"), "hits": doc.get("hits", []),
        "source": source_label, "data": meta, "note": doc.get("note"), "engine": ENGINE_VERSION,
        "partial": bool(doc.get("failed")) or bool(doc.get("unconfirmed")),
        "counts": doc.get("counts"),
        "criteria": CRITERIA_DAILY if mode == "daily" else CRITERIA_ORB,
        **({"or_minutes": doc.get("or_minutes"), "unconfirmed": doc.get("unconfirmed")} if mode == "orb" else {}),
    }
    with tx(ctx.user.id, ctx.user.email) as conn:
        conn.execute(update(scan_runs).where(scan_runs.c.id == scan_id).values(status="succeeded", result=result))
    return {"scan_id": str(scan_id), "hits": len(result["hits"]), "scanned": result["scanned"]}


@handler("scan.daily")
def scan_daily(ctx: JobContext) -> dict:
    return _run_scan(ctx)


@handler("scan.orb")
def scan_orb(ctx: JobContext) -> dict:
    return _run_scan(ctx)


def _scan_failed(ctx: JobContext, message: str, status: str) -> None:
    sid = ctx.params.get("scan_id")
    if sid:
        with tx(ctx.user.id, ctx.user.email) as conn:
            conn.execute(update(scan_runs).where(scan_runs.c.id == uuid.UUID(sid)).values(status=status, error=message))


FAILURE_HOOKS["scan.daily"] = _scan_failed
FAILURE_HOOKS["scan.orb"] = _scan_failed


def watchlist_symbols(conn, workspace_id: uuid.UUID, watchlist_id: uuid.UUID) -> list[str]:  # noqa: ANN001
    return [r.symbol for r in conn.execute(select(watchlist_assets.c.symbol).where(
        watchlist_assets.c.workspace_id == workspace_id, watchlist_assets.c.watchlist_id == watchlist_id))]


# ---------------------------------------------------------------- snapshots

def _snapshot_for(ctx: JobContext, symbol: str, snapshot_id: str | None, rng: str, interval: str,
                  plan_day: str | None = None, sessions: int | None = None) -> tuple[dict, str]:
    """A frozen snapshot row and its text: the one asked for, or a fresh download frozen now.

    New 5-minute bars come from the provider chosen by DP_INTRADAY_PROVIDER (Alpaca when its keys
    are set, in auto); everything else from Yahoo. If that provider is off or fails, the run fails
    with its reason: there is no silent switch to another source."""
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
            return dict(row), md.read_snapshot_text(row["sha256"], ctx.user.workspace_id)
        except md.DataError as e:
            raise JobFailure(e.message)
    if providers.bars_provider(interval) == alpaca.PROVIDER_ID:
        n = int(sessions or alpaca.DEFAULT_SESSIONS)
        day = datetime.strptime(plan_day, "%Y-%m-%d").date() if plan_day else None
        ctx.progress(10, f"Baixando {n} sessões de candles de 5 min de {symbol} "
                         f"(Alpaca, feed {alpaca.feed().upper()})")
        try:
            text, fetched, quality = alpaca.fetch_session_chart(symbol, day, n)
        except alpaca.AlpacaError as e:
            raise JobFailure(e.message, e.code)
        try:
            with tx(ctx.user.id, ctx.user.email) as conn:
                row = md.freeze_snapshot(conn, ctx.user.workspace_id, ctx.user.id, text, symbol, interval,
                                         f"{n}sess", alpaca.source(quality["feed"]), fetched)
        except md.DataError as e:
            raise JobFailure(e.message, e.code)
        return row, text
    ctx.progress(10, f"Baixando {rng} de candles de {interval} de {symbol}")
    try:
        text, fetched, _ = md.fetch_chart_raw(symbol, rng, interval, use_cache=False)
    except md.DataError as e:
        raise JobFailure(e.message, e.code)
    try:
        with tx(ctx.user.id, ctx.user.email) as conn:
            row = md.freeze_snapshot(conn, ctx.user.workspace_id, ctx.user.id, text, symbol, interval, rng,
                                     md.SOURCE, fetched)
    except md.DataError as e:
        raise JobFailure(e.message, e.code)
    return row, text


def _data_quality(snap: dict, text: str, before: str | None = None) -> dict | None:
    """The coverage report of an Alpaca snapshot, recomputed from the frozen text (so a
    reproduction shows the same report). None for other sources."""
    if not alpaca.is_alpaca_source(snap.get("source")):
        return None
    try:
        return alpaca.session_quality(text, datetime.strptime(before, "%Y-%m-%d").date() if before else None)
    except (KeyError, ValueError, TypeError):
        return None


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
    snap, text = _snapshot_for(ctx, p["symbol"], p.get("snapshot_id"), "60d", "5m", plan_day=p["date"],
                               sessions=p.get("history_sessions"))
    _set_experiment(ctx, exp_id, data_snapshot_id=snap["id"])
    if p.get("plan_rule"):
        # The plan kept on the server: trader-entry + trader-exit on the plan day inside this same
        # snapshot. The prices stay in the results (to reproduce the run); the API decides what to show.
        rule = p["plan_rule"]
        ctx.progress(20, "Calculando o plano ORB no servidor (trader-entry + trader-exit)")
        try:
            got = orb_plan.compute(text, p["symbol"], datetime.strptime(p["date"], "%Y-%m-%d").date(),
                                   int(rule["or_minutes"]), rule["stop_rule"], float(rule["stop_pct"]),
                                   float(rule["atr_k"]), float(rule["target_r"]))
        except orb_plan.PlanRefusal as e:
            raise JobFailure(str(e), "entry_error")
        if not got.get("plan"):
            raise JobFailure(got.get("refusal") or f"A regra ORB não disparou em {p['date']}: {got.get('reason')}.",
                             "plan_not_triggered")
        p = {**p, **{k: got["plan"][k] for k in ("entry", "stop", "target", "entry_time")}}
    quality = _data_quality(snap, text, p["date"])
    if quality is not None:
        # Clear reasons before the engine runs; the engine itself is unchanged and checks again.
        why = alpaca.entry_bar_check(text, datetime.strptime(p["date"], "%Y-%m-%d").date(), p["entry_time"])
        if why:
            raise JobFailure(why, "entry_bar_missing")
        if quality["pool_sessions"] < alpaca.MIN_SESSIONS:
            raise JobFailure(
                f"Só {quality['pool_sessions']} sessões completas (78 candles) antes de {p['date']} no feed {quality['feed'].upper()}; "
                f"o Time Machine precisa de {alpaca.MIN_SESSIONS}. {len(quality['incomplete_sessions'])} sessões "
                "encerradas tiveram lacunas e ficaram de fora. Peça mais sessões de histórico.", "not_enough_sessions")
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
        "snapshot": _snapshot_ref(snap),
        "data_quality": quality,
        "algorithm_version": ENGINE_VERSION + " / timemachine",
        "limitations": [
            "Simulação construída a partir das sessões recentes do próprio ativo. Não é previsão.",
            "Os candles de 5 min são sorteados um a um, sem dependência entre eles: tendência e mudanças de volatilidade do dia não são modeladas.",
            "Gap através do stop conta como -1R; um candle que toca stop e alvo conta como stop. Sem custos nem slippage.",
            "Eventos ausentes da janela (resultados, notícias, suspensões) não aparecem nas simulações.",
            *([alpaca.limitation(snap.get("source"))] if quality is not None else []),
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


def _snapshot_ref(snap: dict) -> dict:
    """What a result records about its data: the frozen payload (content hash) and its origin."""
    fx = bool(snap.get("is_fixture"))
    return {"id": str(snap["id"]), "sha256": snap["sha256"], "source": snap["source"],
            "fetched_at": _iso(snap["fetched_at"]), "is_fixture": fx,
            "provenance": providers.provenance_for_source(snap["source"], fx)}


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
        snap, text = _snapshot_for(ctx, symbol, p.get("snapshot_id"), "60d", "5m",
                                   sessions=p.get("history_sessions"))
        ctx.progress(50, "Reexecutando a regra ORB em cada sessão")
        try:
            out = backtest_orb(text, symbol, cfg, split)
        except BacktestError as e:
            raise JobFailure(str(e))
        quality = _data_quality(snap, text)
        if quality is not None:
            out["data_quality"] = quality
            out["assumptions"] = [*out["assumptions"], alpaca.limitation(snap.get("source"))]
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
               "snapshot": _snapshot_ref(snap)}
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
