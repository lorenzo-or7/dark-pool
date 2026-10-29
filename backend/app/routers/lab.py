"""Strategy Lab, Time Machine, backtests, snapshots and market replay, jobs,
simulated risk sizing, Analytics and exports."""

from __future__ import annotations

import csv
import datetime as dt
import io
import uuid
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import delete, desc, func, select, update

from ..auth import CurrentUser, current_user
from ..db import (data_snapshots, experiments, new_id, now, simulated_trades, simulation_runs, strategies,
                  strategy_versions, tx)
from ..engines.runner import load_module
from ..schemas import (BacktestRequest, OrbPlanRequest, RiskCheckRequest, StrategyCreate, StrategyUpdate,
                       TimeMachineRequest)
from ..services import jobs as jobsvc
from ..services import market_data as md
from ..services.backtest import RULE_LABELS
from ..services.metrics import summarize
from ..services.tasks import strategy_config
from .common import audit, bad_request, not_found, rows, ser

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])
NY = ZoneInfo("America/New_York")


# ---------------------------------------------------------------- strategies

@router.get("/strategies/rules")
def rule_catalog() -> dict:
    from ..schemas import PARAM_LIMITS
    return {"rules": [{"type": k, "label": RULE_LABELS[k], "interval": "5m" if k == "orb" else "1d",
                       "params": {p: {"min": lo, "max": hi, "default": d} for p, (lo, hi, d) in v.items()}}
                      for k, v in PARAM_LIMITS.items()]}


@router.get("/strategies")
def list_strategies(user: CurrentUser = Depends(current_user), archived: bool = False) -> list[dict]:
    with tx(user.id, user.email) as conn:
        out = rows(conn.execute(select(strategies).where(strategies.c.workspace_id == user.workspace_id,
                                                         strategies.c.archived.is_(archived))
                                .order_by(desc(strategies.c.updated_at))))
        counts = dict(conn.execute(select(experiments.c.strategy_id, func.count()).where(
            experiments.c.workspace_id == user.workspace_id).group_by(experiments.c.strategy_id)).all())
    for s in out:
        s["experiments"] = counts.get(uuid.UUID(s["id"]), 0)
    return out


def _get_strategy(conn, user: CurrentUser, sid: uuid.UUID) -> dict:  # noqa: ANN001
    s = conn.execute(select(strategies).where(strategies.c.id == sid,
                                              strategies.c.workspace_id == user.workspace_id)).mappings().first()
    if s is None:
        raise not_found("Estratégia")
    return dict(s)


@router.get("/strategies/{sid}")
def get_strategy(sid: uuid.UUID, user: CurrentUser = Depends(current_user)) -> dict:
    with tx(user.id, user.email) as conn:
        s = _get_strategy(conn, user, sid)
        versions = rows(conn.execute(select(strategy_versions).where(strategy_versions.c.strategy_id == sid)
                                     .order_by(desc(strategy_versions.c.version))))
        exps = rows(conn.execute(select(experiments.c.id, experiments.c.kind, experiments.c.title,
                                        experiments.c.status, experiments.c.strategy_version, experiments.c.created_at)
                                 .where(experiments.c.strategy_id == sid).order_by(desc(experiments.c.created_at))))
    return {**ser(s), "versions": versions, "experiments": exps}


@router.post("/strategies", status_code=201)
def create_strategy(body: StrategyCreate, user: CurrentUser = Depends(current_user)) -> dict:
    sid = new_id()
    cfg = body.config.model_dump(mode="json")
    with tx(user.id, user.email) as conn:
        conn.execute(strategies.insert().values(
            id=sid, workspace_id=user.workspace_id, name=body.name, description=body.description,
            symbol=cfg["symbol"], rule_type=cfg["rule"]["type"], current_version=1, is_demo=False, archived=False,
            created_by=user.id, updated_by=user.id, created_at=now(), updated_at=now()))
        conn.execute(strategy_versions.insert().values(
            id=new_id(), workspace_id=user.workspace_id, strategy_id=sid, version=1, config=cfg,
            note=body.note or "Versão inicial", created_by=user.id, created_at=now()))
        audit(conn, user, "create", "strategy", sid)
    return get_strategy(sid, user)


@router.patch("/strategies/{sid}")
def update_strategy(sid: uuid.UUID, body: StrategyUpdate, user: CurrentUser = Depends(current_user)) -> dict:
    with tx(user.id, user.email) as conn:
        s = _get_strategy(conn, user, sid)
        values: dict = {"updated_at": now(), "updated_by": user.id}
        for f in ("name", "description", "archived"):
            if getattr(body, f) is not None:
                values[f] = getattr(body, f)
        if body.config is not None:
            cfg = body.config.model_dump(mode="json")
            cur = conn.execute(select(strategy_versions.c.config).where(
                strategy_versions.c.strategy_id == sid, strategy_versions.c.version == s["current_version"])).scalar()
            if cur != cfg:
                v = s["current_version"] + 1
                conn.execute(strategy_versions.insert().values(
                    id=new_id(), workspace_id=user.workspace_id, strategy_id=sid, version=v, config=cfg,
                    note=body.note or f"Versão {v}", created_by=user.id, created_at=now()))
                values.update(current_version=v, symbol=cfg["symbol"], rule_type=cfg["rule"]["type"])
        conn.execute(update(strategies).where(strategies.c.id == sid).values(**values))
        audit(conn, user, "update", "strategy", sid, {"version": values.get("current_version")})
    return get_strategy(sid, user)


@router.post("/strategies/{sid}/duplicate", status_code=201)
def duplicate_strategy(sid: uuid.UUID, user: CurrentUser = Depends(current_user)) -> dict:
    with tx(user.id, user.email) as conn:
        s = _get_strategy(conn, user, sid)
        cfg = conn.execute(select(strategy_versions.c.config).where(
            strategy_versions.c.strategy_id == sid, strategy_versions.c.version == s["current_version"])).scalar()
    from ..schemas import StrategyConfig
    body = StrategyCreate(name=(s["name"] + " (cópia)")[:120], description=s["description"] or "",
                          config=StrategyConfig(**cfg), note=f"Duplicada de {s['name']} v{s['current_version']}")
    return create_strategy(body, user)


@router.delete("/strategies/{sid}", status_code=204)
def delete_strategy(sid: uuid.UUID, user: CurrentUser = Depends(current_user)) -> None:
    with tx(user.id, user.email) as conn:
        _get_strategy(conn, user, sid)
        conn.execute(delete(strategies).where(strategies.c.id == sid))
        audit(conn, user, "delete", "strategy", sid)


# ---------------------------------------------------------------- experiments

def _submit_experiment(user: CurrentUser, job_type: str, kind: str, title: str, params: dict,
                       strategy_id: uuid.UUID | None = None, version: int | None = None,
                       dataset: str = "full") -> dict:
    """Create the experiment and its job together. An identical run still in progress is reused."""
    eid = new_id()

    def created(conn, job_id):  # noqa: ANN001, ANN202
        conn.execute(experiments.insert().values(
            id=eid, workspace_id=user.workspace_id, strategy_id=strategy_id, strategy_version=version, kind=kind,
            title=title[:160], status="queued", params=params, dataset=dataset, job_id=job_id, created_by=user.id,
            created_at=now(), updated_at=now()))
        audit(conn, user, "create", "experiment", eid, {"kind": kind})

    job, was_created = jobsvc.submit(user, job_type, {**params, "experiment_id": str(eid)}, on_created=created,
                                     dedupe_params=params)
    return {"job": ser(job), "created": was_created, "experiment_id": job["params"]["experiment_id"]}


@router.post("/timemachine", status_code=status.HTTP_202_ACCEPTED)
def run_timemachine(body: TimeMachineRequest, user: CurrentUser = Depends(current_user)) -> dict:
    params = body.model_dump(mode="json", exclude={"title"})
    title = body.title or (f"Time Machine · {body.symbol} {body.date.isoformat()} {body.entry_time} · "
                           f"{body.replays:,} replays · seed {body.seed}").replace(",", ".")
    return _submit_experiment(user, "timemachine.run", "monte_carlo", title, params,
                              strategy_id=body.strategy_id)


@router.post("/backtests", status_code=status.HTTP_202_ACCEPTED)
def run_backtest(body: BacktestRequest, user: CurrentUser = Depends(current_user)) -> dict:
    with tx(user.id, user.email) as conn:
        try:
            cfg, version, name = strategy_config(conn, user.workspace_id, body.strategy_id, body.version)
        except LookupError:
            raise not_found("Estratégia ou versão")
    params = {"strategy_id": str(body.strategy_id), "version": version, "config": cfg, "range": body.range,
              "snapshot_id": str(body.snapshot_id) if body.snapshot_id else None,
              "split_date": body.split_date.isoformat() if body.split_date else None}
    title = f"Backtest · {name} v{version} · {cfg['symbol']}"
    return _submit_experiment(user, "backtest.run", "backtest", title, params, strategy_id=body.strategy_id,
                              version=version, dataset="split" if body.split_date else "full")


@router.get("/experiments")
def list_experiments(user: CurrentUser = Depends(current_user), kind: str | None = None,
                     strategy_id: uuid.UUID | None = None, limit: int = Query(50, ge=1, le=200)) -> list[dict]:
    q = (select(experiments.c.id, experiments.c.kind, experiments.c.title, experiments.c.status,
                experiments.c.params, experiments.c.strategy_id, experiments.c.strategy_version, experiments.c.dataset,
                experiments.c.error, experiments.c.job_id, experiments.c.data_snapshot_id, experiments.c.created_by,
                experiments.c.created_at, experiments.c.updated_at)
         .where(experiments.c.workspace_id == user.workspace_id).order_by(desc(experiments.c.created_at)).limit(limit))
    if kind:
        q = q.where(experiments.c.kind == kind)
    if strategy_id:
        q = q.where(experiments.c.strategy_id == strategy_id)
    with tx(user.id, user.email) as conn:
        return rows(conn.execute(q))


@router.get("/experiments/{eid}")
def get_experiment(eid: uuid.UUID, user: CurrentUser = Depends(current_user)) -> dict:
    with tx(user.id, user.email) as conn:
        e = conn.execute(select(experiments).where(experiments.c.id == eid,
                                                   experiments.c.workspace_id == user.workspace_id)).mappings().first()
        if e is None:
            raise not_found("Experimento")
        sim = conn.execute(select(simulation_runs).where(simulation_runs.c.experiment_id == eid)).mappings().first()
        trades = rows(conn.execute(select(simulated_trades).where(simulated_trades.c.experiment_id == eid)
                                   .order_by(simulated_trades.c.entry_date, simulated_trades.c.entry_time)))
    return {**ser(dict(e)), "simulation": ser(dict(sim)) if sim else None, "trades": trades}


@router.delete("/experiments/{eid}", status_code=204)
def delete_experiment(eid: uuid.UUID, user: CurrentUser = Depends(current_user)) -> None:
    with tx(user.id, user.email) as conn:
        r = conn.execute(delete(experiments).where(experiments.c.id == eid,
                                                   experiments.c.workspace_id == user.workspace_id,
                                                   experiments.c.status.notin_(("queued", "running"))))
        if not r.rowcount:
            raise bad_request("Experimento inexistente ou ainda em execução.")
        audit(conn, user, "delete", "experiment", eid)


@router.get("/experiments/{eid}/export")
def export_experiment(eid: uuid.UUID, format: Literal["json", "csv"] = "json",  # noqa: A002
                      user: CurrentUser = Depends(current_user)) -> Response:
    e = get_experiment(eid, user)
    name = f"darkpool-{e['kind']}-{str(eid)[:8]}"
    if format == "json":
        import json
        body = json.dumps({"exported_at": now().isoformat(), "experiment": e}, ensure_ascii=False, indent=1)
        return Response(body, media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{name}.json"'})
    buf = io.StringIO()
    cols = ["symbol", "source", "dataset", "entry_date", "entry_time", "entry", "stop", "target", "exit_price",
            "exit_date", "outcome", "r_multiple"]
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for t in e["trades"]:
        w.writerow(t)
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}-trades.csv"'})


# ---------------------------------------------------------------- jobs

@router.get("/jobs/{job_id}")
def get_job(job_id: uuid.UUID, user: CurrentUser = Depends(current_user)) -> dict:
    j = jobsvc.get(user, job_id)
    if j is None:
        raise not_found("Tarefa")
    j.pop("dedupe_key", None)
    return ser(j)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: uuid.UUID, user: CurrentUser = Depends(current_user)) -> dict:
    if not jobsvc.request_cancel(user, job_id):
        raise bad_request("A tarefa não está em execução.")
    return {"cancel_requested": True}


# ---------------------------------------------------------------- snapshots and replay

@router.get("/snapshots")
def list_snapshots(user: CurrentUser = Depends(current_user), symbol: str | None = None,
                   interval: str | None = None) -> list[dict]:
    q = (select(data_snapshots).where(data_snapshots.c.workspace_id == user.workspace_id)
         .order_by(desc(data_snapshots.c.fetched_at)).limit(100))
    if symbol:
        q = q.where(data_snapshots.c.symbol == symbol.upper())
    if interval:
        q = q.where(data_snapshots.c.interval == interval)
    with tx(user.id, user.email) as conn:
        return rows(conn.execute(q))


@router.post("/snapshots/fixture", status_code=201)
def register_fixture(user: CurrentUser = Depends(current_user)) -> dict:
    with tx(user.id, user.email) as conn:
        row = md.register_fixture(conn, user.workspace_id, user.id)
        if row is None:
            raise not_found("Arquivo de referência TSLA-60d5m")
        audit(conn, user, "register", "snapshot", row["id"], {"fixture": True})
    return ser(row)


def _snapshot(user: CurrentUser, sid: uuid.UUID) -> tuple[dict, md.Chart]:
    with tx(user.id, user.email) as conn:
        s = conn.execute(select(data_snapshots).where(data_snapshots.c.id == sid,
                                                      data_snapshots.c.workspace_id == user.workspace_id)
                         ).mappings().first()
    if s is None:
        raise not_found("Snapshot")
    try:
        return dict(s), md.parse_chart(md.read_snapshot_text(s["sha256"]), s["symbol"])
    except md.DataError as e:
        raise HTTPException(409, {"code": e.code, "message": e.message})


def _session_bars(chart: md.Chart) -> dict[str, list[dict]]:
    days: dict[str, list[dict]] = {}
    for b in chart.bars:
        t = dt.datetime.fromtimestamp(b["time"], NY)
        mins = t.hour * 60 + t.minute
        if b["time"] % 300 or not 570 <= mins < 960:
            continue
        days.setdefault(t.date().isoformat(), []).append({**b, "et": t.strftime("%H:%M")})
    return days


@router.get("/snapshots/{sid}/sessions")
def snapshot_sessions(sid: uuid.UUID, user: CurrentUser = Depends(current_user)) -> dict:
    s, chart = _snapshot(user, sid)
    if s["interval"] != "5m":
        raise bad_request("O replay usa snapshots de candles de 5 minutos.")
    days = _session_bars(chart)
    return {"snapshot": ser(s), "sessions": [{"date": d, "bars": len(v), "full": len(v) == 78}
                                             for d, v in sorted(days.items())]}


@router.get("/snapshots/{sid}/bars")
def snapshot_bars(sid: uuid.UUID, date: dt.date, user: CurrentUser = Depends(current_user)) -> dict:
    s, chart = _snapshot(user, sid)
    bars = _session_bars(chart).get(date.isoformat())
    if not bars:
        raise not_found("Sessão")
    return {"symbol": s["symbol"], "date": date.isoformat(), "timezone": "America/New_York", "bars": bars,
            "snapshot": {"id": str(s["id"]), "sha256": s["sha256"], "source": s["source"]}}


# ---------------------------------------------------------------- ORB plan (trader-entry + trader-exit)

@router.post("/plan/orb")
def orb_plan(body: OrbPlanRequest, user: CurrentUser = Depends(current_user)) -> dict:
    """The day's opening-range breakout from a frozen snapshot: trader-entry finds the
    trigger bar, trader-exit sets the stop and the target. Pure calls, no network."""
    s, _ = _snapshot(user, body.snapshot_id)
    if s["interval"] != "5m":
        raise bad_request("O plano ORB precisa de um snapshot de candles de 5 minutos.")
    entry, exitm = load_module("entry"), load_module("exit")
    text = md.read_snapshot_text(s["sha256"])
    close_utc = entry.eastern_to_utc(dt.datetime.combine(body.date, dt.time(16, 5)))
    try:
        chart = entry.parse_chart(text, s["symbol"])
        res = entry.evaluate(chart, close_utc, setup="orb", or_minutes=body.or_minutes, interval="5m")
    except entry.EntryError as e:
        raise bad_request(str(e), "entry_error")
    pub = entry.public(res)
    orr, trig = pub.get("opening_range"), pub.get("trigger")
    if pub["status"] != "triggered" or not trig or not orr:
        return {"triggered": False, "status": pub["status"], "reason": pub.get("reason"), "opening_range": orr,
                "engine": "trader-entry"}
    try:
        plan = exitm.compute(exitm.D(str(trig["price"])), body.stop_rule, exitm.D(str(body.stop_pct)), "r",
                             exitm.D(str(body.target_r)),
                             or_high=orr["high"], or_low=orr["low"])
    except exitm.PlanError as e:
        return {"triggered": True, "plan": None, "refusal": str(e), "trigger": trig, "opening_range": orr}
    hh, mm = (int(x) for x in str(trig["time"])[:5].split(":"))
    return {
        "triggered": True, "trigger": trig, "opening_range": orr, "reason": pub.get("reason"),
        "plan": {"symbol": s["symbol"], "date": body.date.isoformat(), "entry_time": f"{hh:02d}:{mm:02d}",
                 "entry": float(plan["entry"]), "stop": float(plan["stop"]), "target": float(plan["target"]),
                 "risk_per_share": float(plan["risk"]), "stop_label": plan["stop_label"],
                 "target_label": plan["target_label"]},
        "engine": "trader-entry + trader-exit",
    }


# ---------------------------------------------------------------- simulated risk and sizing

@router.post("/risk/check")
def risk_check(body: RiskCheckRequest) -> dict:
    """trader-budget and trader-risk as pure functions, in a simulated context. Nothing is sent anywhere."""
    size, check = load_module("budget"), load_module("risk")
    r = body.risk
    cfg = {"budget": r.account_size, "cash_buffer_pct": 0, "max_position_pct": r.max_position_pct,
           "max_order_usd": r.account_size, "max_loss_per_trade_usd": r.max_loss_per_trade,
           "max_daily_loss_usd": r.daily_loss_limit, "max_trades_per_day": r.max_trades_per_day,
           "min_reward_risk": r.min_reward_risk, "require_stop": True, "paper": True, "fractional": False,
           "allow_options": False, "allow_margin": False, "allow_short": False}
    plan = {"symbol": body.symbol, "side": "buy", "date": body.date.isoformat(), "entry": body.entry,
            "stop": body.stop, "target": body.target, "entry_time": body.entry_time, "setup": "orb"}
    try:
        sized = size.size_trade(plan, cfg)
    except size.SizeError as e:
        return {"sizing": None, "refusal": str(e), "risk": None, "simulated": True}
    order = size.bracket_order(sized)
    risk = None
    if order:
        local = dt.datetime.combine(body.date, dt.time.fromisoformat(body.entry_time))
        now_utc = check.eastern_to_utc(local)
        res = check.check([order], cfg, now=now_utc, today=body.date.isoformat())
        risk = {"pass": res["pass"], "block": res["block"], "warnings": res.get("warnings", []),
                "results": [{k: v for k, v in x.items() if k in ("verdict", "reasons", "warnings", "checks")}
                            for x in res["results"]]}
    keep = ("symbol", "qty", "entry", "stop", "target", "risk_per_share", "max_loss", "position_usd", "bound_by",
            "refusal", "reward_risk", "notes")
    return {"sizing": {k: v for k, v in sized.items() if k in keep}, "risk": risk, "simulated": True,
            "note": "Cálculo simulado com trader-budget e trader-risk. Nenhuma ordem é criada ou enviada."}


# ---------------------------------------------------------------- analytics

@router.get("/analytics")
def analytics(user: CurrentUser = Depends(current_user), experiment_id: uuid.UUID | None = None,
              dataset: Literal["all", "development", "out_of_sample"] = "all") -> dict:
    with tx(user.id, user.email) as conn:
        exps = rows(conn.execute(
            select(experiments.c.id, experiments.c.title, experiments.c.kind, experiments.c.created_at,
                   experiments.c.strategy_id, experiments.c.dataset)
            .where(experiments.c.workspace_id == user.workspace_id, experiments.c.status == "succeeded")
            .order_by(desc(experiments.c.created_at))))
        if experiment_id is None and exps:
            experiment_id = uuid.UUID(exps[0]["id"])
        trades = []
        if experiment_id:
            q = select(simulated_trades).where(simulated_trades.c.workspace_id == user.workspace_id,
                                               simulated_trades.c.experiment_id == experiment_id)
            if dataset != "all":
                q = q.where(simulated_trades.c.dataset == dataset)
            trades = rows(conn.execute(q))
    sel = next((e for e in exps if e["id"] == str(experiment_id)), None)
    return {"experiments": exps, "selected": sel, "dataset": dataset, "summary": summarize(trades),
            "source_kind": None if not trades else trades[0]["source"]}


@router.get("/analytics/compare")
def compare(ids: str = Query(min_length=36, max_length=37 * 6), user: CurrentUser = Depends(current_user)) -> dict:
    try:
        wanted = [uuid.UUID(x) for x in ids.split(",") if x.strip()][:6]
    except ValueError:
        raise bad_request("ids inválidos")
    out = []
    with tx(user.id, user.email) as conn:
        for eid in wanted:
            e = conn.execute(select(experiments.c.id, experiments.c.title, experiments.c.kind, experiments.c.results)
                             .where(experiments.c.id == eid, experiments.c.workspace_id == user.workspace_id)
                             ).mappings().first()
            if e is None:
                continue
            trades = rows(conn.execute(select(simulated_trades).where(simulated_trades.c.experiment_id == eid)))
            res = e["results"] or {}
            out.append({"id": str(eid), "title": e["title"], "kind": e["kind"], "summary": summarize(trades),
                        "period": {"from": res.get("first_date") or (res.get("mc") or {}).get("pool_from"),
                                   "to": res.get("last_date") or (res.get("mc") or {}).get("pool_to")},
                        "snapshot": (res.get("snapshot") or {}).get("sha256")})
    periods = {(x["period"]["from"], x["period"]["to"]) for x in out}
    return {"items": out, "same_period": len(periods) <= 1,
            "warning": None if len(periods) <= 1 else
            "Os experimentos cobrem períodos diferentes: a comparação não é sob condições equivalentes."}
