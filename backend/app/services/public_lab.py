"""Idempotent setup of the public shared lab: the technical identity that the backend
uses for every visitor, as a member of one existing workspace.

Postgres (Supabase): calls public.dp_setup_public_lab(), created by the migration
20261030000100_public_shared_lab.sql. It must run with the database owner's connection
(DATABASE_URL on the server). It never deletes or rewrites workspace data.

SQLite (local development): writes the same profile and membership rows directly.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, text

from ..auth import PUBLIC_DISPLAY_NAME, public_identity_id, reset_public_cache
from ..db import create_demo_schema, get_engine, now, profiles, workspace_members, workspaces


class SetupError(Exception):
    pass


def setup_public_lab(workspace_id: uuid.UUID, identity_id: uuid.UUID | None = None) -> dict:
    """-> {"workspace_id", "workspace_name", "identity_id"}. Safe to run any number of times."""
    ident = identity_id or public_identity_id(workspace_id)
    eng = get_engine()
    if eng.dialect.name == "postgresql":
        with eng.begin() as conn:
            row = conn.execute(text("select * from public.dp_setup_public_lab(:ws, :id)"),
                               {"ws": str(workspace_id), "id": str(ident)}).mappings().first()
        reset_public_cache()
        return {"workspace_id": str(workspace_id), "workspace_name": row["workspace_name"],
                "identity_id": str(row["identity_id"])}

    create_demo_schema()
    with eng.begin() as conn:
        ws = conn.execute(select(workspaces.c.name).where(workspaces.c.id == workspace_id)).first()
        if ws is None:
            raise SetupError(f"O workspace {workspace_id} não existe neste banco.")
        other = conn.execute(select(workspace_members.c.workspace_id).where(
            workspace_members.c.user_id == ident, workspace_members.c.workspace_id != workspace_id)).first()
        if other is not None:
            raise SetupError("A identidade técnica já pertence a outro workspace.")
        p = conn.execute(select(profiles.c.id).where(profiles.c.id == ident)).first()
        if p is None:
            conn.execute(profiles.insert().values(id=ident, email=None, display_name=PUBLIC_DISPLAY_NAME,
                                                  preferences={}, created_at=now(), updated_at=now()))
        m = conn.execute(select(workspace_members.c.role).where(
            workspace_members.c.user_id == ident, workspace_members.c.workspace_id == workspace_id)).first()
        if m is None:
            conn.execute(workspace_members.insert().values(workspace_id=workspace_id, user_id=ident, role="member",
                                                           created_at=now()))
    reset_public_cache()
    return {"workspace_id": str(workspace_id), "workspace_name": ws.name, "identity_id": str(ident)}
