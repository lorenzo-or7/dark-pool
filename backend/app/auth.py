"""Who is calling: Supabase JWT verification (or the local demo session) and
workspace membership. Every private route depends on `current_user`."""

from __future__ import annotations

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
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise _unauthorized("faça login para continuar")
    token = header[7:].strip()
    if s.is_demo:
        host = request.client.host if request.client else ""
        if token != DEMO_TOKEN or host not in LOOPBACK:
            raise _unauthorized("sessão de demonstração aceita apenas localmente")
        return _membership(DEMO_USER_ID, "demo@darkpool.local")
    claims = verify_supabase_token(token)
    try:
        uid = uuid.UUID(claims["sub"])
    except ValueError:
        raise _unauthorized("token sem usuário válido")
    return _membership(uid, claims.get("email") or "")


def owner_only(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if user.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, {"code": "forbidden", "message": "Apenas o proprietário."})
    return user
