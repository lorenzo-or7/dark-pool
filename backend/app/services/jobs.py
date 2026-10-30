"""Background jobs: created by a request, run on a small thread pool outside the
HTTP request, with progress, cancellation, de-duplication and a time limit."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import threading
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from sqlalchemy import desc, func, select, update

from ..auth import CurrentUser
from ..config import get_settings
from ..db import experiments, jobs, now, scan_runs, tx
from ..engines.runner import EngineCancelled, EngineTimeout

ACTIVE = ("queued", "running")
log = logging.getLogger("darkpool.jobs")
# Longest engine run a job may make (scan.daily allows up to 900 s), plus downloads and margin.
_MAX_ENGINE_S = 900
# job id -> client key, for the per-client cap. Lost on restart, like the jobs themselves.
_job_clients: dict[uuid.UUID, str] = {}
_pool: ThreadPoolExecutor | None = None
# One process: serializes the "already running? / queue full?" check with the insert.
_submit_lock = threading.Lock()


INTERRUPTED_RESTART = "A tarefa foi interrompida porque o servidor reiniciou. Rode de novo para repetir."
INTERRUPTED_STALE = "A tarefa foi interrompida (o servidor pode ter reiniciado ou suspendido)."


class QueueFull(Exception):
    """Too many jobs queued or running in the workspace."""


class JobFailure(Exception):
    """A clean, user-facing failure (the message is shown as is)."""

    def __init__(self, message: str, code: str = "job_failed"):
        super().__init__(message)
        self.code = code


@dataclass
class JobContext:
    job_id: uuid.UUID
    user: CurrentUser
    params: dict
    workdir: Path

    def progress(self, pct: int, stage: str) -> None:
        with tx(self.user.id, self.user.email) as conn:
            conn.execute(update(jobs).where(jobs.c.id == self.job_id)
                         .values(progress=max(0, min(100, int(pct))), stage=stage[:200]))

    def cancelled(self) -> bool:
        with tx(self.user.id, self.user.email) as conn:
            return bool(conn.execute(select(jobs.c.cancel_requested).where(jobs.c.id == self.job_id)).scalar())


Handler = Callable[[JobContext], dict]
HANDLERS: dict[str, Handler] = {}


def handler(name: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        HANDLERS[name] = fn
        return fn
    return deco


def _executor() -> ThreadPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ThreadPoolExecutor(max_workers=get_settings().dp_job_workers, thread_name_prefix="dp-job")
    return _pool


def dedupe_key(job_type: str, params: dict) -> str:
    return hashlib.sha256((job_type + json.dumps(params, sort_keys=True, default=str)).encode()).hexdigest()


def submit(user: CurrentUser, job_type: str, params: dict,
           on_created: Callable[[object, uuid.UUID], None] | None = None,
           dedupe_params: dict | None = None) -> tuple[dict, bool]:
    """-> (job row, created). An identical active job in the workspace is returned instead of a new one.
    `dedupe_params` leaves out ids generated per request (an experiment id, a scan id)."""
    if job_type not in HANDLERS:
        raise ValueError(f"unknown job type {job_type}")
    key = dedupe_key(job_type, params if dedupe_params is None else dedupe_params)
    with _submit_lock, tx(user.id, user.email) as conn:
        existing = conn.execute(select(jobs).where(jobs.c.workspace_id == user.workspace_id,
                                                   jobs.c.dedupe_key == key, jobs.c.status.in_(ACTIVE))
                                ).mappings().first()
        if existing:
            return dict(existing), False
        active_ids = [r[0] for r in conn.execute(select(jobs.c.id).where(
            jobs.c.workspace_id == user.workspace_id, jobs.c.status.in_(ACTIVE))).all()]
        s = get_settings()
        if len(active_ids) >= s.dp_max_active_jobs:
            raise QueueFull(f"A fila do laboratório está cheia ({len(active_ids)} tarefas em andamento). "
                            "Aguarde uma terminar e tente de novo.")
        from ..limits import current_client
        client = current_client.get()
        for jid in [j for j in _job_clients if j not in set(active_ids)]:
            _job_clients.pop(jid, None)
        mine = sum(1 for j in active_ids if _job_clients.get(j) == client)
        if client != "unknown" and mine >= s.dp_max_active_jobs_per_client:
            raise QueueFull(f"Você já tem {mine} tarefas em andamento. Aguarde uma terminar para iniciar outra.")
        job_id = uuid.uuid4()
        row = {"id": job_id, "workspace_id": user.workspace_id, "type": job_type, "params": params,
               "dedupe_key": key, "status": "queued", "progress": 0, "stage": "Na fila",
               "cancel_requested": False, "created_by": user.id, "created_at": now()}
        conn.execute(jobs.insert().values(**row))
        if on_created:
            on_created(conn, job_id)
        _job_clients[job_id] = client
    _executor().submit(_run, job_id, user, job_type, params)
    return row, True


def _finish(user: CurrentUser, job_id: uuid.UUID, **values: object) -> None:
    # Only a job that is still active: one closed as interrupted stays closed.
    with tx(user.id, user.email) as conn:
        conn.execute(update(jobs).where(jobs.c.id == job_id, jobs.c.status.in_(ACTIVE))
                     .values(finished_at=now(), **values))


def _run(job_id: uuid.UUID, user: CurrentUser, job_type: str, params: dict) -> None:
    workdir = get_settings().dp_data_dir / "jobs" / str(job_id)
    ctx = JobContext(job_id, user, params, workdir)
    try:
        if ctx.cancelled():
            _finish(user, job_id, status="cancelled", stage="Cancelado antes de iniciar")
            _notify_failure(ctx, job_type, "Cancelado antes de iniciar.", "cancelled")
            return
        with tx(user.id, user.email) as conn:
            claimed = conn.execute(update(jobs).where(jobs.c.id == job_id, jobs.c.status == "queued")
                                   .values(status="running", started_at=now(), stage="Iniciando")).rowcount
        if not claimed:
            return  # closed meanwhile (interrupted or cancelled): do not run it
        result = HANDLERS[job_type](ctx)
        _finish(user, job_id, status="succeeded", progress=100, stage="Concluído", result=result)
    except EngineCancelled:
        _finish(user, job_id, status="cancelled", stage="Cancelado")
        _notify_failure(ctx, job_type, "Cancelado pelo usuário.", "cancelled")
    except EngineTimeout as e:
        _finish(user, job_id, status="failed", stage="Tempo esgotado", error=str(e))
        _notify_failure(ctx, job_type, str(e), "failed")
    except JobFailure as e:
        _finish(user, job_id, status="failed", stage="Falhou", error=str(e))
        _notify_failure(ctx, job_type, str(e), "failed")
    except Exception as e:  # noqa: BLE001 - recorded, never swallowed silently
        # Details go to the server log only: job errors are visible to every visitor.
        log.error("job %s (%s) failed", job_id, job_type, exc_info=True)
        msg = f"Erro interno ({type(e).__name__}). A falha foi registrada no servidor."
        _finish(user, job_id, status="failed", stage="Falhou", error=msg)
        _notify_failure(ctx, job_type, msg, "failed")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


FAILURE_HOOKS: dict[str, Callable[[JobContext, str, str], None]] = {}


def _notify_failure(ctx: JobContext, job_type: str, message: str, status: str) -> None:
    hook = FAILURE_HOOKS.get(job_type)
    if hook:
        try:
            hook(ctx, message, status)
        except Exception:  # noqa: BLE001
            traceback.print_exc()


def _interrupt(conn, job_ids: list, message: str) -> None:  # noqa: ANN001
    """Close jobs that can never finish, and the experiments and scans that wait on them."""
    if not job_ids:
        return
    conn.execute(update(jobs).where(jobs.c.id.in_(job_ids), jobs.c.status.in_(ACTIVE)).values(
        status="failed", stage="Interrompido", finished_at=now(), error=message))
    conn.execute(update(experiments).where(experiments.c.job_id.in_(job_ids),
                                           experiments.c.status.in_(ACTIVE)).values(
        status="failed", error=message, updated_at=now()))
    conn.execute(update(scan_runs).where(scan_runs.c.job_id.in_(job_ids), scan_runs.c.status.in_(ACTIVE)).values(
        status="failed", error=message))


def _stale(row: dict) -> bool:
    """A job that can no longer be running in any process. Only a fallback: restarts are
    handled at startup. Running: longer than any engine allows. Queued: longer than a full
    queue could take."""
    s = get_settings()
    run_limit = timedelta(seconds=max(s.dp_job_timeout_s, _MAX_ENGINE_S) + 300)
    if row["status"] == "running" and row.get("started_at"):
        return now() - _aware(row["started_at"]) > run_limit
    if row["status"] == "queued" and row.get("created_at"):
        return now() - _aware(row["created_at"]) > run_limit * (s.dp_max_active_jobs + 1)
    return False


def get(user: CurrentUser, job_id: uuid.UUID) -> dict | None:
    with tx(user.id, user.email) as conn:
        row = conn.execute(select(jobs).where(jobs.c.id == job_id, jobs.c.workspace_id == user.workspace_id)
                           ).mappings().first()
        if row is None:
            return None
        row = dict(row)
        if _stale(row):
            _interrupt(conn, [job_id], INTERRUPTED_STALE)
            row.update(status="failed", stage="Interrompido", error=INTERRUPTED_STALE)
        return row


def list_recent(user: CurrentUser, since_minutes: int = 30, limit: int = 30) -> list[dict]:
    """Jobs of the workspace that are active, or ended in the last `since_minutes`."""
    since = now() - timedelta(minutes=since_minutes)
    with tx(user.id, user.email) as conn:
        # Every active job (there are at most dp_max_active_jobs), then the recently ended ones.
        found = [dict(r) for r in conn.execute(
            select(jobs).where(jobs.c.workspace_id == user.workspace_id, jobs.c.status.in_(ACTIVE))
            .order_by(desc(jobs.c.created_at)).limit(200)).mappings()]
        found += [dict(r) for r in conn.execute(
            select(jobs).where(jobs.c.workspace_id == user.workspace_id, jobs.c.status.notin_(ACTIVE),
                               jobs.c.finished_at >= since)
            .order_by(desc(jobs.c.finished_at)).limit(limit)).mappings()]
        stale = [r["id"] for r in found if _stale(r)]
        if stale:
            _interrupt(conn, stale, INTERRUPTED_STALE)
            for r in found:
                if r["id"] in stale:
                    r.update(status="failed", stage="Interrompido", error=INTERRUPTED_STALE, finished_at=now())
        exp_ids = [uuid.UUID(r["params"]["experiment_id"]) for r in found
                   if isinstance(r.get("params"), dict) and r["params"].get("experiment_id")]
        titles = {}
        if exp_ids:
            titles = {str(i): t for i, t in conn.execute(
                select(experiments.c.id, experiments.c.title).where(
                    experiments.c.workspace_id == user.workspace_id, experiments.c.id.in_(exp_ids))).all()}
    for r in found:
        eid = (r.get("params") or {}).get("experiment_id")
        r["title"] = titles.get(str(eid)) if eid else None
    return found


def _aware(d):  # noqa: ANN001, ANN202 - SQLite returns naive datetimes
    from datetime import UTC
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def request_cancel(user: CurrentUser, job_id: uuid.UUID) -> bool:
    with tx(user.id, user.email) as conn:
        res = conn.execute(update(jobs).where(jobs.c.id == job_id, jobs.c.workspace_id == user.workspace_id,
                                              jobs.c.status.in_(ACTIVE)).values(cancel_requested=True))
        return res.rowcount > 0


def mark_orphans_failed_sqlite() -> None:
    """Demo database only: jobs left active by a previous process can never finish."""
    from ..db import get_engine
    eng = get_engine()
    if eng.dialect.name != "sqlite":
        return
    with eng.begin() as conn:
        ids = [r[0] for r in conn.execute(select(jobs.c.id).where(jobs.c.status.in_(ACTIVE))).all()]
        _interrupt(conn, ids, INTERRUPTED_RESTART)


def mark_interrupted_on_start(user: CurrentUser) -> int:
    """Shared lab on start: jobs left queued/running in its workspace by a previous process (a
    restart, a deploy, a free instance spun down) are closed as interrupted, never left running.
    Runs as the lab identity, so RLS limits it to the lab's workspace."""
    with tx(user.id, user.email) as conn:
        ids = [r[0] for r in conn.execute(select(jobs.c.id).where(
            jobs.c.workspace_id == user.workspace_id, jobs.c.status.in_(ACTIVE))).all()]
        _interrupt(conn, ids, INTERRUPTED_RESTART)
    return len(ids)
