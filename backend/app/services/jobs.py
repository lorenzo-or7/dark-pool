"""Background jobs: created by a request, run on a small thread pool outside the
HTTP request, with progress, cancellation, de-duplication and a time limit."""

from __future__ import annotations

import hashlib
import json
import shutil
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select, update

from ..auth import CurrentUser
from ..config import get_settings
from ..db import jobs, now, tx
from ..engines.runner import EngineCancelled, EngineTimeout

ACTIVE = ("queued", "running")
_pool: ThreadPoolExecutor | None = None


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
    with tx(user.id, user.email) as conn:
        existing = conn.execute(select(jobs).where(jobs.c.workspace_id == user.workspace_id,
                                                   jobs.c.dedupe_key == key, jobs.c.status.in_(ACTIVE))
                                ).mappings().first()
        if existing:
            return dict(existing), False
        job_id = uuid.uuid4()
        row = {"id": job_id, "workspace_id": user.workspace_id, "type": job_type, "params": params,
               "dedupe_key": key, "status": "queued", "progress": 0, "stage": "Na fila",
               "cancel_requested": False, "created_by": user.id, "created_at": now()}
        conn.execute(jobs.insert().values(**row))
        if on_created:
            on_created(conn, job_id)
    _executor().submit(_run, job_id, user, job_type, params)
    return row, True


def _finish(user: CurrentUser, job_id: uuid.UUID, **values: object) -> None:
    with tx(user.id, user.email) as conn:
        conn.execute(update(jobs).where(jobs.c.id == job_id).values(finished_at=now(), **values))


def _run(job_id: uuid.UUID, user: CurrentUser, job_type: str, params: dict) -> None:
    workdir = get_settings().dp_data_dir / "jobs" / str(job_id)
    ctx = JobContext(job_id, user, params, workdir)
    try:
        if ctx.cancelled():
            _finish(user, job_id, status="cancelled", stage="Cancelado antes de iniciar")
            _notify_failure(ctx, job_type, "Cancelado antes de iniciar.", "cancelled")
            return
        with tx(user.id, user.email) as conn:
            conn.execute(update(jobs).where(jobs.c.id == job_id)
                         .values(status="running", started_at=now(), stage="Iniciando"))
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
        traceback.print_exc()
        msg = f"Erro interno: {type(e).__name__}: {e}"
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


def get(user: CurrentUser, job_id: uuid.UUID) -> dict | None:
    with tx(user.id, user.email) as conn:
        row = conn.execute(select(jobs).where(jobs.c.id == job_id, jobs.c.workspace_id == user.workspace_id)
                           ).mappings().first()
        if row is None:
            return None
        row = dict(row)
        limit = timedelta(seconds=get_settings().dp_job_timeout_s + 120)
        stale_from = row.get("started_at") or row["created_at"]
        if row["status"] in ACTIVE and stale_from and now() - _aware(stale_from) > limit:
            conn.execute(update(jobs).where(jobs.c.id == job_id).values(
                status="failed", stage="Interrompido", finished_at=now(),
                error="A tarefa foi interrompida (o servidor pode ter reiniciado)."))
            row.update(status="failed", stage="Interrompido",
                       error="A tarefa foi interrompida (o servidor pode ter reiniciado).")
        return row


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
        conn.execute(update(jobs).where(jobs.c.status.in_(ACTIVE)).values(
            status="failed", stage="Interrompido", finished_at=now(),
            error="A tarefa foi interrompida porque o servidor reiniciou."))
