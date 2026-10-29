"""DARK POOL API. Research and simulation only: there is no order route and no
broker integration anywhere in this application."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import APP_VERSION, get_settings
from .routers import journal, lab, market, system
from .services import tasks  # noqa: F401 - registers the job handlers
from .services.jobs import mark_orphans_failed_sqlite


@asynccontextmanager
async def lifespan(_: FastAPI):  # noqa: ANN201
    s = get_settings()
    if s.is_demo and not s.is_postgres:
        from .services.seed import bootstrap_demo
        bootstrap_demo()
        mark_orphans_failed_sqlite()
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="DARK POOL API", version=APP_VERSION, lifespan=lifespan,
                  docs_url="/api/docs" if s.is_demo else None, openapi_url="/api/openapi.json" if s.is_demo else None)
    app.add_middleware(CORSMiddleware, allow_origins=s.origins, allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                       allow_headers=["Authorization", "Content-Type"])

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
