"""Who is calling, and in which workspace. Every private route depends on `current_user`.

- demo:     the local SQLite workspace, loopback only.
- supabase: a Supabase Auth JWT and the member's own workspace.
- public:   the shared lab. Nobody logs in; the server runs every request as a dedicated
            technical identity, a member of DP_PUBLIC_WORKSPACE_ID only. The identity is chosen
            here, from server settings; nothing in the request (headers, ids, roles, claims)
            can change it."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select

from .config import get_settings
from .db import profiles, tx, workspace_members, workspaces

DEMO_TOKEN = "demo-local"
DEMO_USER_ID = uuid.UUID("00000000-0000-4000-8000-00000000d001")
DEMO_WORKSPACE_ID = uuid.UUID("00000000-0000-4000-8000-00000000a001")
LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}
PUBLIC_ROLE = "public"
PUBLIC_DISPLAY_NAME = "Laboratório compartilhado"
# Fixed namespace: the technical identity of a workspace is always the same UUID.
_PUBLIC_NS = uuid.UUID("6f2b8d4e-1c0a-4f53-9d7e-5a1b2c3d4e5f")


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    email: str
    display_name: str
    workspace_id: uuid.UUID
    workspace_name: str
    role: str
    is_demo: bool


def _unauthorized(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, {"code": "unauthorized", "message": msg},
                         headers={"WWW-Authenticate": "Bearer"})


@lru_cache
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=3600, timeout=10)


def verify_supabase_token(token: str) -> dict:
    s = get_settings()
    if not s.supabase_url:
        raise _unauthorized("SUPABASE_URL não configurada no backend")
    issuer = s.supabase_url.rstrip("/") + "/auth/v1"
    try:
        alg = jwt.get_unverified_header(token).get("alg", "")
        if alg == "HS256":
            if not s.supabase_jwt_secret:
                raise _unauthorized("token HS256 sem SUPABASE_JWT_SECRET configurado")
            key = s.supabase_jwt_secret
        elif alg in ("RS256", "ES256"):
            key = _jwks_client(issuer + "/.well-known/jwks.json").get_signing_key_from_jwt(token).key
        else:
            raise _unauthorized("algoritmo de token não aceito")
        claims = jwt.decode(token, key, algorithms=[alg], audience="authenticated", issuer=issuer,
                            options={"require": ["exp", "sub"]})
    except jwt.ExpiredSignatureError:
        raise _unauthorized("sessão expirada")
    except jwt.PyJWTError:
        raise _unauthorized("token inválido")
    if claims.get("role") != "authenticated":
        raise _unauthorized("token sem papel authenticated")
    return claims


class PublicLabUnavailable(Exception):
    """The public mode is on but its workspace or technical identity is not set up."""


def public_workspace_id() -> uuid.UUID:
    raw = get_settings().dp_public_workspace_id.strip()
    if not raw:
        raise PublicLabUnavailable("DP_PUBLIC_WORKSPACE_ID não está configurado no backend.")
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise PublicLabUnavailable("DP_PUBLIC_WORKSPACE_ID não é um UUID válido.")


def public_identity_id(workspace_id: uuid.UUID | None = None) -> uuid.UUID:
    raw = get_settings().dp_public_identity_id.strip()
    if raw:
        try:
            return uuid.UUID(raw)
        except ValueError:
            raise PublicLabUnavailable("DP_PUBLIC_IDENTITY_ID não é um UUID válido.")
    return uuid.uuid5(_PUBLIC_NS, f"darkpool-public-lab:{workspace_id or public_workspace_id()}")


_public_cache: tuple[float, CurrentUser] | None = None
_public_lock = threading.Lock()
PUBLIC_CACHE_S = 30.0


def reset_public_cache() -> None:
    global _public_cache
    with _public_lock:
        _public_cache = None


def _resolve_public() -> CurrentUser:
    ws = public_workspace_id()
    ident = public_identity_id(ws)
    with tx(ident, "") as conn:
        row = conn.execute(
            select(workspace_members.c.role, workspaces.c.name, workspaces.c.is_demo)
            .join(workspaces, workspaces.c.id == workspace_members.c.workspace_id)
            .where(workspace_members.c.user_id == ident, workspace_members.c.workspace_id == ws)
        ).first()
    if row is None:
        raise PublicLabUnavailable(
            "O workspace público não foi preparado: rode scripts/setup_public_lab.py com o "
            "DP_PUBLIC_WORKSPACE_ID configurado.")
    if row.role == "owner":
        # The technical identity is never an administrator of the workspace.
        raise PublicLabUnavailable("A identidade técnica do laboratório não pode ser proprietária do workspace.")
    return CurrentUser(id=ident, email="", display_name=PUBLIC_DISPLAY_NAME, workspace_id=ws,
                       workspace_name=row.name, role=PUBLIC_ROLE, is_demo=bool(row.is_demo))


def public_lab_user() -> CurrentUser:
    """The shared lab's context, checked against the database at most every 30 s."""
    global _public_cache
    with _public_lock:
        hit = _public_cache
    if hit and time.monotonic() - hit[0] < PUBLIC_CACHE_S:
        return hit[1]
    user = _resolve_public()
    with _public_lock:
        _public_cache = (time.monotonic(), user)
    return user


def _membership(user_id: uuid.UUID, email: str) -> CurrentUser:
    with tx(user_id, email) as conn:
        row = conn.execute(
            select(workspace_members.c.workspace_id, workspace_members.c.role, workspaces.c.name,
                   workspaces.c.is_demo, profiles.c.display_name, profiles.c.email)
            .join(workspaces, workspaces.c.id == workspace_members.c.workspace_id)
            .join(profiles, profiles.c.id == workspace_members.c.user_id)
            .where(workspace_members.c.user_id == user_id)
            .order_by(workspace_members.c.created_at)
            .limit(1)
        ).first()
    if row is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            {"code": "not_a_member", "message": "Esta conta não tem acesso a nenhum workspace."})
    return CurrentUser(id=user_id, email=row.email or email, display_name=row.display_name or email.split("@")[0],
                       workspace_id=row.workspace_id, workspace_name=row.name, role=row.role,
                       is_demo=bool(row.is_demo))


def current_user(request: Request) -> CurrentUser:
    s = get_settings()
    if s.is_public:
        # Authorization headers, ids and claims sent by the visitor are ignored on purpose.
        try:
            return public_lab_user()
        except PublicLabUnavailable as e:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                                {"code": "public_lab_unconfigured", "message": str(e)})
    header = request.headers.get("authorization", "")
    if s.is_demo:
        # Local demo: the browser no longer holds a session. Loopback only, as before.
        host = request.client.host if request.client else ""
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""
        if host not in LOOPBACK or (header and token != DEMO_TOKEN):
            raise _unauthorized("sessão de demonstração aceita apenas localmente")
        return _membership(DEMO_USER_ID, "demo@darkpool.local")
    if not header.lower().startswith("bearer "):
        raise _unauthorized("faça login para continuar")
    token = header[7:].strip()
    claims = verify_supabase_token(token)
    try:
        uid = uuid.UUID(claims["sub"])
    except ValueError:
        raise _unauthorized("token sem usuário válido")
    return _membership(uid, claims.get("email") or "")


def owner_only(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    """Administrative actions. The public lab identity is never an owner, so these stay closed
    to visitors. (No API route uses it today: membership is managed by scripts/invite_member.py.)"""
    if user.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, {"code": "forbidden", "message": "Apenas o proprietário."})
    return user
