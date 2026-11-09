"""House PTRs (Bloco 10). See services/congress.py; off in the public lab unless DP_PELOSI_PUBLIC=true."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ..auth import current_user
from ..services import congress

router = APIRouter(prefix="/api", tags=["congress"], dependencies=[Depends(current_user)])


def _err(e: congress.CongressError) -> JSONResponse:
    return JSONResponse({"detail": {"code": e.code, "message": e.message}}, status_code=e.status)


@router.get("/congress/ptrs")
def list_ptrs(year: int = Query(default_factory=lambda: dt.date.today().year, ge=2008, le=2100),
              member: str | None = Query(None, max_length=60), since: dt.date | None = None,
              limit: int = Query(100, ge=1, le=500)):
    try:
        return congress.index(year, [member] if member else None, since.isoformat() if since else None, limit)
    except congress.CongressError as e:
        return _err(e)


@router.get("/congress/ptrs/{doc_id}")
def get_ptr(doc_id: str, year: int = Query(default_factory=lambda: dt.date.today().year, ge=2008, le=2100),
            filed: dt.date | None = None):
    try:
        return congress.report(doc_id, year, filed.isoformat() if filed else None)
    except congress.CongressError as e:
        return _err(e)
