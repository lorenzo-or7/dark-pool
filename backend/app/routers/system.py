"""Health, public config, the signed-in user, workspace and dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, func, select, update

from ..auth import CurrentUser, PublicLabUnavailable, current_user, public_lab_user
from ..config import APP_VERSION, ENGINE_VERSION, get_settings
from ..db import (data_snapshots, experiments, jobs, profiles, scan_runs, strategies, tx, workspace_members,
                  workspaces)
from ..engines.runner import script_path
from ..schemas import ProfileUpdate
from ..services import policy, providers, storage
from ..services.tasks import universe_path
from .common import audit, rows, ser

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict:
    s = get_settings()
    engines = {}
    for name in ("scanner", "timemachine", "entry", "exit", "budget", "risk", "news", "analyst", "alerts"):
        try:
            script_path(name)
            engines[name] = "ok"
        except Exception:  # noqa: BLE001
            engines[name] = "missing"
    out = {"status": "ok", "version": APP_VERSION, "engine": ENGINE_VERSION, "mode": s.dp_auth_mode,
           "database": "postgres" if s.is_postgres else "sqlite", "engines": engines,
           "storage": storage.backend(), "broker": "not_integrated"}
    try:
        from ..services import market_calendar as mcal
        cov = mcal.coverage()
        out["calendar"] = {"status": "warning" if cov["warnings"] else "ok", "engine_years": cov["engine_years"],
                           "server_to": cov["server_range"]["to"], "warnings": cov["warnings"]}
    except Exception:  # noqa: BLE001 - the calendar never takes the health check down
        out["calendar"] = {"status": "unavailable"}
    if s.is_public:
        # Only a yes/no and a plain reason: no ids, hosts, keys or database details.
        try:
            public_lab_user()
            out["public_lab"] = "ready"
        except PublicLabUnavailable as e:
            out["public_lab"] = "unconfigured"
            out["status"] = "degraded"
            out["detail"] = str(e)
        except Exception:  # noqa: BLE001 - e.g. the database is unreachable
            out["public_lab"] = "unavailable"
            out["status"] = "degraded"
            out["detail"] = "Banco de dados indisponível."
    return out


@router.get("/config")
def public_config() -> dict:
    s = get_settings()
    return {"auth_mode": s.dp_auth_mode, "access": "public" if s.is_public else "private",
            "version": APP_VERSION, "signup": False}


@router.get("/me")
def me(user: CurrentUser = Depends(current_user)) -> dict:
    if get_settings().is_public:
        # The shared lab context. No account, e-mail, user id or member data.
        return {"mode": "public", "display_name": user.display_name, "role": user.role,
                "workspace": {"id": str(user.workspace_id), "name": user.workspace_name, "is_demo": user.is_demo},
                "preferences": {}}
    with tx(user.id, user.email) as conn:
        p = conn.execute(select(profiles).where(profiles.c.id == user.id)).mappings().first()
    return {"mode": get_settings().dp_auth_mode, "id": str(user.id), "email": user.email,
            "display_name": user.display_name, "role": user.role,
            "workspace": {"id": str(user.workspace_id), "name": user.workspace_name, "is_demo": user.is_demo},
            "preferences": (p or {}).get("preferences") or {}}


@router.patch("/me")
def update_me(body: ProfileUpdate, user: CurrentUser = Depends(current_user)) -> dict:
    if get_settings().is_public:
        raise HTTPException(status.HTTP_403_FORBIDDEN, {
            "code": "preferences_in_browser",
            "message": "No laboratório compartilhado as preferências ficam salvas neste navegador."})
    values = body.model_dump(exclude_none=True)
    if values:
        with tx(user.id, user.email) as conn:
            if "preferences" in values:
                cur = conn.execute(select(profiles.c.preferences).where(profiles.c.id == user.id)).scalar() or {}
                values["preferences"] = {**cur, **values["preferences"]}
            conn.execute(update(profiles).where(profiles.c.id == user.id).values(**values))
            audit(conn, user, "update", "profile", user.id, {"fields": sorted(values)})
    return me(user)


def _data_sources(last_snap: dict, universe) -> list[dict]:  # noqa: ANN001
    """Every provider's state for the Settings page. Never keys, hosts or account details.
    last_snap: latest non-fixture snapshot time per provider id."""
    last = {**{k: ser(v) for k, v in last_snap.items()},
            "nasdaq_trader": ser(_mtime(universe)) if universe.exists() else None}
    return [{**p, "last_fetch": last.get(p["id"], p["last_success"])} for p in providers.status()]


@router.get("/workspace")
def workspace(user: CurrentUser = Depends(current_user)) -> dict:
    s = get_settings()
    with tx(user.id, user.email) as conn:
        ws = conn.execute(select(workspaces).where(workspaces.c.id == user.workspace_id)).mappings().first()
        members = [] if s.is_public else rows(conn.execute(
            select(workspace_members.c.user_id, workspace_members.c.role, workspace_members.c.created_at,
                   profiles.c.email, profiles.c.display_name)
            .join(profiles, profiles.c.id == workspace_members.c.user_id)
            .where(workspace_members.c.workspace_id == user.workspace_id)
            .order_by(workspace_members.c.created_at)))
        last_by_source = conn.execute(select(data_snapshots.c.source, func.max(data_snapshots.c.fetched_at))
                                      .where(data_snapshots.c.workspace_id == user.workspace_id,
                                             data_snapshots.c.is_fixture.is_(False))
                                      .group_by(data_snapshots.c.source)).all()
    last_snap: dict = {}
    for source, when in last_by_source:
        pid = providers.SOURCE_PROVIDER.get(source)
        if pid and when is not None and (pid not in last_snap or when > last_snap[pid]):
            last_snap[pid] = when
    u = universe_path()
    if s.is_public and ws:
        # Only what the lab page shows; workspace settings and members stay private.
        ws = {k: ws[k] for k in ("id", "name", "is_demo", "created_at")}
    return {
        "workspace": ser(dict(ws)) if ws else None, "members": members, "shared": s.is_public,
        "data_sources": _data_sources(last_snap, u),
        "intraday_provider": providers.intraday_summary(),
        "display_policy": policy.summary(),
        "version": {"app": APP_VERSION, "engine": ENGINE_VERSION, "mode": s.dp_auth_mode,
                    "database": "postgres" if s.is_postgres else "sqlite"},
    }


def _mtime(p):  # noqa: ANN001, ANN202
    from datetime import UTC, datetime
    return datetime.fromtimestamp(p.stat().st_mtime, UTC)


@router.get("/dashboard")
def dashboard(user: CurrentUser = Depends(current_user)) -> dict:
    ws = user.workspace_id
    with tx(user.id, user.email) as conn:
        n_strat = conn.execute(select(func.count()).select_from(strategies).where(
            strategies.c.workspace_id == ws, strategies.c.archived.is_(False))).scalar()
        n_exp = conn.execute(select(func.count()).select_from(experiments).where(
            experiments.c.workspace_id == ws, experiments.c.status == "succeeded")).scalar()
        recent = rows(conn.execute(
            select(experiments.c.id, experiments.c.kind, experiments.c.title, experiments.c.status,
                   experiments.c.created_at, experiments.c.updated_at, experiments.c.error, experiments.c.strategy_id,
                   experiments.c.params)
            .where(experiments.c.workspace_id == ws).order_by(desc(experiments.c.created_at)).limit(8)))
        backtests = rows(conn.execute(
            select(experiments.c.id, experiments.c.title, experiments.c.created_at)
            .where(experiments.c.workspace_id == ws, experiments.c.kind == "backtest",
                   experiments.c.status == "succeeded").order_by(desc(experiments.c.created_at)).limit(20)))
        last_snap = conn.execute(select(data_snapshots.c.symbol, data_snapshots.c.fetched_at, data_snapshots.c.source,
                                        data_snapshots.c.interval)
                                 .where(data_snapshots.c.workspace_id == ws, data_snapshots.c.is_fixture.is_(False))
                                 .order_by(desc(data_snapshots.c.fetched_at)).limit(1)).mappings().first()
        last_scan = conn.execute(select(scan_runs.c.created_at, scan_runs.c.status)
                                 .where(scan_runs.c.workspace_id == ws)
                                 .order_by(desc(scan_runs.c.created_at)).limit(1)).mappings().first()
        active_jobs = conn.execute(select(func.count()).select_from(jobs).where(
            jobs.c.workspace_id == ws, jobs.c.status.in_(("queued", "running")))).scalar()
    return {
        "counts": {"strategies": n_strat, "experiments": n_exp, "active_jobs": active_jobs},
        "recent_experiments": recent,
        "backtests": backtests,
        "last_data": ser(dict(last_snap)) if last_snap else None,
        "last_scan": ser(dict(last_scan)) if last_scan else None,
    }
