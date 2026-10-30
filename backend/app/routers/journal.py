"""Trading Journal: shared research entries with tags, links to strategies and
experiments, simulated trades and chart captures."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import delete, desc, func, or_, select, update

from ..auth import CurrentUser, current_user
from ..config import get_settings
from ..db import attachments, experiments, journal_entries, new_id, now, profiles, strategies, tx
from ..schemas import JournalWrite
from ..services import storage
from .common import audit, bad_request, not_found, rows, ser

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])
IMAGE_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
MAX_BYTES = 5 * 1024 * 1024  # also enforced by the attachments table and bucket


def _max_bytes() -> int:
    return min(MAX_BYTES, get_settings().dp_max_upload_bytes)


def _check_links(conn, user: CurrentUser, body: JournalWrite) -> None:  # noqa: ANN001
    if body.strategy_id and conn.execute(select(strategies.c.id).where(
            strategies.c.id == body.strategy_id, strategies.c.workspace_id == user.workspace_id)).first() is None:
        raise bad_request("Estratégia vinculada não existe neste workspace.")
    if body.experiment_id and conn.execute(select(experiments.c.id).where(
            experiments.c.id == body.experiment_id, experiments.c.workspace_id == user.workspace_id)).first() is None:
        raise bad_request("Experimento vinculado não existe neste workspace.")


def _values(body: JournalWrite) -> dict:
    d = body.model_dump(mode="json")
    d["entry_date"] = body.entry_date.isoformat()
    d["strategy_id"] = body.strategy_id
    d["experiment_id"] = body.experiment_id
    return d


@router.get("/journal")
def list_entries(user: CurrentUser = Depends(current_user), q: str | None = Query(None, max_length=80),
                 tag: str | None = Query(None, max_length=32), kind: str | None = None,
                 date_from: str | None = None, date_to: str | None = None,
                 limit: int = Query(100, ge=1, le=500)) -> list[dict]:
    if get_settings().is_public:
        # Shared lab: entries are the lab's, not a person's. No names or e-mails of past authors.
        stmt = select(journal_entries).where(journal_entries.c.workspace_id == user.workspace_id)
    else:
        author = profiles.alias("author")
        stmt = (select(journal_entries, author.c.display_name.label("author_name"),
                       author.c.email.label("author_email"))
                .join(author, author.c.id == journal_entries.c.created_by, isouter=True)
                .where(journal_entries.c.workspace_id == user.workspace_id))
    stmt = (stmt
            .order_by(desc(journal_entries.c.entry_date), desc(journal_entries.c.created_at)).limit(limit))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(journal_entries.c.title.ilike(like), journal_entries.c.body.ilike(like),
                              journal_entries.c.symbol.ilike(like)))
    if kind:
        stmt = stmt.where(journal_entries.c.kind == kind)
    if date_from:
        stmt = stmt.where(journal_entries.c.entry_date >= date_from[:10])
    if date_to:
        stmt = stmt.where(journal_entries.c.entry_date <= date_to[:10])
    with tx(user.id, user.email) as conn:
        out = rows(conn.execute(stmt))
        atts = rows(conn.execute(select(attachments.c.id, attachments.c.journal_entry_id, attachments.c.filename,
                                        attachments.c.content_type, attachments.c.size)
                                 .where(attachments.c.workspace_id == user.workspace_id)))
    if tag:
        out = [e for e in out if tag.lower() in (e.get("tags") or [])]
    for e in out:
        e["attachments"] = [a for a in atts if a["journal_entry_id"] == e["id"]]
    return out


@router.post("/journal", status_code=201)
def create_entry(body: JournalWrite, user: CurrentUser = Depends(current_user)) -> dict:
    eid = new_id()
    with tx(user.id, user.email) as conn:
        _check_links(conn, user, body)
        conn.execute(journal_entries.insert().values(
            id=eid, workspace_id=user.workspace_id, is_demo=False, created_by=user.id, updated_by=user.id,
            created_at=now(), updated_at=now(), **_values(body)))
        audit(conn, user, "create", "journal_entry", eid)
        row = conn.execute(select(journal_entries).where(journal_entries.c.id == eid)).mappings().first()
    out = {**ser(dict(row)), "attachments": []}
    if not get_settings().is_public:
        out["author_name"] = user.display_name
    return out


@router.put("/journal/{eid}")
def update_entry(eid: uuid.UUID, body: JournalWrite, user: CurrentUser = Depends(current_user)) -> dict:
    with tx(user.id, user.email) as conn:
        _check_links(conn, user, body)
        r = conn.execute(update(journal_entries).where(journal_entries.c.id == eid,
                                                       journal_entries.c.workspace_id == user.workspace_id)
                         .values(updated_by=user.id, updated_at=now(), **_values(body)))
        if not r.rowcount:
            raise not_found("Registro")
        audit(conn, user, "update", "journal_entry", eid)
        row = conn.execute(select(journal_entries).where(journal_entries.c.id == eid)).mappings().first()
    return ser(dict(row))


@router.delete("/journal/{eid}", status_code=204)
def delete_entry(eid: uuid.UUID, request: Request, user: CurrentUser = Depends(current_user)) -> None:
    with tx(user.id, user.email) as conn:
        files = conn.execute(select(attachments).where(attachments.c.journal_entry_id == eid,
                                                       attachments.c.workspace_id == user.workspace_id)).mappings().all()
        r = conn.execute(delete(journal_entries).where(journal_entries.c.id == eid,
                                                       journal_entries.c.workspace_id == user.workspace_id))
        if not r.rowcount:
            raise not_found("Registro")
        audit(conn, user, "delete", "journal_entry", eid)
    for f in files:
        _remove_file(dict(f), request)


# ---------------------------------------------------------------- attachments

def _local_dir() -> Path:
    d = get_settings().dp_data_dir / "attachments"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _bearer(request: Request) -> str:
    return request.headers.get("authorization", "") if get_settings().dp_auth_mode == "supabase" else ""


def _remove_file(row: dict, request: Request) -> None:
    if row["storage"] == "local":
        (_local_dir() / Path(row["path"]).name).unlink(missing_ok=True)
    else:
        try:
            storage.delete(storage.BUCKET_ATTACHMENTS, row["path"], row["workspace_id"], _bearer(request))
        except storage.StorageError:
            pass


@router.post("/journal/{eid}/attachments", status_code=201)
async def upload_attachment(eid: uuid.UUID, request: Request, file: UploadFile = File(...),
                            user: CurrentUser = Depends(current_user)) -> dict:
    ext = IMAGE_TYPES.get(file.content_type or "")
    if not ext:
        raise bad_request("Envie uma imagem PNG, JPEG ou WebP.")
    limit = _max_bytes()
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, {"code": "too_large", "message": f"Imagem acima de {limit // (1024 * 1024)} MB."})
    sig = {"png": b"\x89PNG", "jpg": b"\xff\xd8", "webp": b"RIFF"}[ext]
    if not data.startswith(sig):
        raise bad_request("O conteúdo do arquivo não corresponde ao tipo informado.")
    with tx(user.id, user.email) as conn:
        if conn.execute(select(journal_entries.c.id).where(journal_entries.c.id == eid,
                                                           journal_entries.c.workspace_id == user.workspace_id)
                        ).first() is None:
            raise not_found("Registro")
        used = conn.execute(select(func.coalesce(func.sum(attachments.c.size), 0)).where(
            attachments.c.workspace_id == user.workspace_id)).scalar() or 0
    if used + len(data) > get_settings().dp_max_attachment_storage_mb * 1024 * 1024:
        raise HTTPException(507, {"code": "storage_full",
                                  "message": "O espaço para imagens do laboratório acabou. Exclua anexos antigos."})
    aid = new_id()
    if storage.backend() == "local":
        kind, path = "local", f"{aid}.{ext}"
        (_local_dir() / path).write_bytes(data)
    else:
        kind, path = "supabase", storage.object_key(user.workspace_id, str(eid), f"{aid}.{ext}")
        try:
            storage.put(storage.BUCKET_ATTACHMENTS, path, data, file.content_type or "", user.workspace_id,
                        _bearer(request))
        except storage.StorageError as e:
            raise bad_request(str(e), "storage_error")
    name = Path(file.filename or f"captura.{ext}").name[:200]
    with tx(user.id, user.email) as conn:
        conn.execute(attachments.insert().values(id=aid, workspace_id=user.workspace_id, journal_entry_id=eid,
                                                 filename=name, content_type=file.content_type, size=len(data),
                                                 storage=kind, path=path, created_by=user.id, created_at=now()))
        audit(conn, user, "upload", "attachment", aid)
    return {"id": str(aid), "filename": name, "content_type": file.content_type, "size": len(data)}


@router.get("/attachments/{aid}")
def get_attachment(aid: uuid.UUID, request: Request, user: CurrentUser = Depends(current_user)) -> Response:
    with tx(user.id, user.email) as conn:
        a = conn.execute(select(attachments).where(attachments.c.id == aid,
                                                   attachments.c.workspace_id == user.workspace_id)).mappings().first()
    if a is None:
        raise not_found("Anexo")
    if a["storage"] == "local":
        p = _local_dir() / Path(a["path"]).name
        if not p.exists():
            raise not_found("Arquivo do anexo")
        data = p.read_bytes()
    else:
        try:
            data = storage.get(storage.BUCKET_ATTACHMENTS, a["path"], user.workspace_id, _bearer(request))
        except storage.StorageError:
            data = None
        if data is None:
            raise not_found("Arquivo do anexo")
    return Response(data, media_type=a["content_type"], headers={"Cache-Control": "private, max-age=300",
                                                                 "X-Content-Type-Options": "nosniff"})


@router.delete("/attachments/{aid}", status_code=204)
def delete_attachment(aid: uuid.UUID, request: Request, user: CurrentUser = Depends(current_user)) -> None:
    with tx(user.id, user.email) as conn:
        a = conn.execute(select(attachments).where(attachments.c.id == aid,
                                                   attachments.c.workspace_id == user.workspace_id)).mappings().first()
        if a is None:
            raise not_found("Anexo")
        conn.execute(delete(attachments).where(attachments.c.id == aid))
        audit(conn, user, "delete", "attachment", aid)
    _remove_file(dict(a), request)
