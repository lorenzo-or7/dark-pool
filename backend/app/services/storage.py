"""File storage for snapshots and journal captures.

- local:    files under DP_DATA_DIR (development, the local demo).
- supabase: private Supabase Storage buckets. Only the backend talks to Storage, with the
            server-side key (SUPABASE_SERVICE_ROLE_KEY); the browser never receives a URL or
            a key for these objects. Object names always start with the workspace id, taken
            from the server-side identity, never from the request.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import httpx

from ..config import get_settings

BUCKET_SNAPSHOTS = "snapshots"
BUCKET_ATTACHMENTS = "attachments"
_KEY_RE = re.compile(r"^[0-9a-f-]{36}/[A-Za-z0-9._/-]{1,300}$")


class StorageError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def object_key(workspace_id: uuid.UUID, *parts: str) -> str:
    key = "/".join([str(workspace_id), *parts])
    if not _KEY_RE.match(key) or ".." in key:
        raise StorageError("nome de objeto inválido")
    return key


def _check(key: str, workspace_id: uuid.UUID) -> None:
    if not _KEY_RE.match(key) or ".." in key or not key.startswith(f"{workspace_id}/"):
        raise StorageError("objeto fora do workspace")


def _headers(user_bearer: str | None = None) -> dict:
    s = get_settings()
    key = s.supabase_service_role_key
    if key:
        h = {"apikey": key}
        # Legacy service_role keys are JWTs and go in Authorization too; new sb_secret_ keys must not.
        if key.startswith("eyJ"):
            h["Authorization"] = f"Bearer {key}"
        return h
    # Legacy supabase-auth mode without a server key: act with the member's own token (RLS on Storage).
    return {"apikey": s.supabase_anon_key, "Authorization": user_bearer or ""}


def _url(bucket: str, key: str) -> str:
    return f"{get_settings().supabase_url.rstrip('/')}/storage/v1/object/{bucket}/{key}"


def _local(bucket: str, key: str) -> Path:
    p = get_settings().dp_data_dir / "storage" / bucket / key
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def backend() -> str:
    s = get_settings()
    if s.storage_backend == "supabase":
        return "supabase"
    if s.dp_auth_mode == "supabase" and s.supabase_url:
        return "supabase"  # previous behaviour of the members-only mode
    return "local"


def put(bucket: str, key: str, data: bytes, content_type: str, workspace_id: uuid.UUID,
        user_bearer: str | None = None) -> None:
    _check(key, workspace_id)
    if backend() == "local":
        _local(bucket, key).write_bytes(data)
        return
    try:
        r = httpx.post(_url(bucket, key), content=data, timeout=60,
                       headers={**_headers(user_bearer), "Content-Type": content_type, "x-upsert": "true"})
    except httpx.HTTPError as e:
        raise StorageError(f"Supabase Storage indisponível: {type(e).__name__}") from e
    if r.status_code >= 300:
        raise StorageError(f"O Supabase Storage recusou o arquivo (HTTP {r.status_code}).", r.status_code)


def get(bucket: str, key: str, workspace_id: uuid.UUID, user_bearer: str | None = None) -> bytes | None:
    """-> the object's bytes, or None when it does not exist."""
    _check(key, workspace_id)
    if backend() == "local":
        p = _local(bucket, key)
        return p.read_bytes() if p.exists() else None
    try:
        r = httpx.get(_url(bucket, key).replace("/object/", "/object/authenticated/", 1)
                      if not get_settings().supabase_service_role_key else _url(bucket, key),
                      headers=_headers(user_bearer), timeout=60)
    except httpx.HTTPError as e:
        raise StorageError(f"Supabase Storage indisponível: {type(e).__name__}") from e
    if r.status_code in (400, 404):
        return None
    if r.status_code != 200:
        raise StorageError(f"Supabase Storage respondeu HTTP {r.status_code}.", r.status_code)
    return r.content


def delete(bucket: str, key: str, workspace_id: uuid.UUID, user_bearer: str | None = None) -> None:
    _check(key, workspace_id)
    if backend() == "local":
        _local(bucket, key).unlink(missing_ok=True)
        return
    try:
        httpx.delete(_url(bucket, key), headers=_headers(user_bearer), timeout=30)
    except httpx.HTTPError:
        pass  # the row is gone; an orphan object is harmless and private
