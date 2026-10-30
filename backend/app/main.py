"""DARK POOL API. Research and simulation only: there is no order route and no
broker integration anywhere in this application."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import limits
from .config import APP_VERSION, get_settings
from .routers import journal, lab, market, system
from .services import tasks  # noqa: F401 - registers the job handlers
from .services.jobs import QueueFull, mark_interrupted_on_start, mark_orphans_failed_sqlite

log = logging.getLogger("darkpool")


@asynccontextmanager
async def lifespan(_: FastAPI):  # noqa: ANN201
    s = get_settings()
    if s.is_demo and not s.is_postgres:
        from .services.seed import bootstrap_demo
        bootstrap_demo()
        mark_orphans_failed_sqlite()
    if s.is_public:
        from .auth import PublicLabUnavailable, public_lab_user
        if not s.is_postgres:
            from .db import create_demo_schema
            create_demo_schema()
        try:
            user = public_lab_user()
            if s.dp_mark_interrupted_on_start:
                n = mark_interrupted_on_start(user)
                if n:
                    log.warning("public lab: %d job(s) left by the previous process marked as interrupted", n)
        except PublicLabUnavailable as e:
            # The API still starts so /api/health can say what is missing; lab routes answer 503.
            log.error("public lab not configured: %s", e)
        except Exception as e:  # noqa: BLE001
            log.error("public lab check failed: %s", type(e).__name__)
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="DARK POOL API", version=APP_VERSION, lifespan=lifespan,
                  docs_url="/api/docs" if s.is_demo else None, openapi_url="/api/openapi.json" if s.is_demo else None)

    @app.middleware("http")
    async def request_limits(request: Request, call_next):  # noqa: ANN001, ANN202
        blocked = limits.check(request)
        return blocked if blocked is not None else await call_next(request)

    # CORS only tells browsers which sites may read responses. It is not access control:
    # in the public mode the API is open by design and protected by the limits above and RLS.
    app.add_middleware(CORSMiddleware, allow_origins=s.origins, allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                       allow_headers=["Authorization", "Content-Type"], expose_headers=["Retry-After"])

    @app.exception_handler(QueueFull)
    async def queue_full(_: Request, exc: QueueFull) -> JSONResponse:
        return JSONResponse({"detail": {"code": "queue_full", "message": str(exc)}}, status_code=429,
                            headers={"Retry-After": "30"})

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # noqa: ANN001, ANN202
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        if request.url.path.startswith("/api/") and "Cache-Control" not in resp.headers:
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"field": ".".join(str(p) for p in e["loc"][1:]) or "body",
                   "message": str(e["msg"]).removeprefix("Value error, ")} for e in exc.errors()]
        return JSONResponse({"detail": {"code": "validation_error",
                                        "message": errors[0]["message"] if errors else "Dados inválidos.",
                                        "errors": errors}}, status_code=422)

    for r in (system.router, market.router, lab.router, journal.router):
        app.include_router(r)
    return app


app = create_app()
