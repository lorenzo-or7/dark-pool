from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import Connection

from ..auth import CurrentUser
from ..db import audit_events, now


# In the shared lab, who wrote a row is not shown: no account ids of past authors.
AUTHOR_KEYS = frozenset({"created_by", "updated_by", "added_by", "actor_id"})


def ser(value: Any) -> Any:
    """Rows -> JSON-ready values. Naive datetimes (SQLite) are UTC."""
    if isinstance(value, dict):
        from ..config import get_settings
        if get_settings().is_public:
            return {k: ser(v) for k, v in value.items() if k not in AUTHOR_KEYS}
        return {k: ser(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [ser(v) for v in value]
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def rows(result) -> list[dict]:  # noqa: ANN001
    return [ser(dict(r)) for r in result.mappings()]


def not_found(what: str = "Registro") -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, {"code": "not_found", "message": f"{what} não encontrado."})


def bad_request(message: str, code: str = "invalid") -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, {"code": code, "message": message})


def calendar_refusal(code: str, message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {"code": code, "message": message})


def audit(conn: Connection, user: CurrentUser, action: str, entity: str, entity_id: object = None,
          detail: dict | None = None) -> None:
    conn.execute(audit_events.insert().values(
        id=uuid.uuid4(), workspace_id=user.workspace_id, actor_id=user.id, action=action, entity=entity,
        entity_id=str(entity_id) if entity_id else None, detail=ser(detail) if detail else None, created_at=now()))
