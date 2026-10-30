"""Prepare the existing DARK POOL workspace for public, shared access. Idempotent.

Run it from your computer (or a Render shell) with the server-side settings in the
environment or in a local, uncommitted .env. Nothing here goes to the browser.

    # 1. find the id of the existing workspace (names and counts only, no e-mails)
    py -3 scripts/setup_public_lab.py --list-workspaces
    # 2. create the technical identity and its membership in that workspace
    py -3 scripts/setup_public_lab.py --workspace-id <uuid>
    # 3. (once) copy snapshots and journal images that only exist on this computer
    #    to the private Supabase Storage buckets, so the hosted backend can read them
    py -3 scripts/setup_public_lab.py --workspace-id <uuid> --upload-local-files backend/.data

Needs: DATABASE_URL (the Supabase Postgres connection string, server only). For --upload-local-files
also SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY. The migrations in supabase/migrations must be applied.

It never deletes, renames or rewrites workspace data: it only adds the technical identity, its
'member' row, and (with --upload-local-files) Storage objects plus the attachment rows' location.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace-id", default=os.environ.get("DP_PUBLIC_WORKSPACE_ID", ""))
    ap.add_argument("--list-workspaces", action="store_true")
    ap.add_argument("--upload-local-files", metavar="DATA_DIR", help="the old backend/.data folder")
    args = ap.parse_args()

    os.environ.setdefault("DP_AUTH_MODE", "public")
    from app.config import get_settings
    s = get_settings()
    if not s.database_url:
        print("DATABASE_URL não está definido (use a connection string do Supabase, só no servidor).")
        return 2

    from sqlalchemy import func, select

    from app.db import attachments, data_snapshots, get_engine, workspace_members, workspaces

    eng = get_engine()
    if args.list_workspaces:
        with eng.begin() as conn:
            for w in conn.execute(select(workspaces.c.id, workspaces.c.name, workspaces.c.created_at)
                                  .order_by(workspaces.c.created_at)).all():
                n = conn.execute(select(func.count()).select_from(workspace_members)
                                 .where(workspace_members.c.workspace_id == w.id)).scalar()
                print(f"{w.id}  {w.name}  (criado {w.created_at:%Y-%m-%d}, {n} membros)")
        return 0

    try:
        ws = uuid.UUID(args.workspace_id)
    except ValueError:
        print("Informe --workspace-id (ou DP_PUBLIC_WORKSPACE_ID) com o UUID do workspace existente.")
        return 2

    from app.services.public_lab import SetupError, setup_public_lab
    try:
        res = setup_public_lab(ws)
    except SetupError as e:
        print(f"Erro: {e}")
        return 1
    except Exception as e:  # noqa: BLE001 - the database's own message is the useful one
        msg = getattr(getattr(e, "orig", None), "diag", None)
        print(f"Erro: {getattr(msg, 'message_primary', None) or e}")
        return 1
    print(f"Workspace: {res['workspace_name']} ({res['workspace_id']})")
    print(f"Identidade técnica: {res['identity_id']} (membro, sem senha, sem login)")
    print(f"Configure no backend: DP_AUTH_MODE=public e DP_PUBLIC_WORKSPACE_ID={res['workspace_id']}")

    if args.upload_local_files:
        return _upload(Path(args.upload_local_files), ws, eng, data_snapshots, attachments)
    return 0


def _upload(data_dir: Path, ws: uuid.UUID, eng, data_snapshots, attachments) -> int:  # noqa: ANN001
    from sqlalchemy import select, update

    from app.config import get_settings
    from app.services import storage

    if get_settings().storage_backend != "supabase":
        print("Para enviar arquivos, defina SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY.")
        return 2
    sent = missing = 0
    with eng.begin() as conn:
        snaps = conn.execute(select(data_snapshots.c.sha256).where(data_snapshots.c.workspace_id == ws)).all()
    for (sha,) in snaps:
        p = data_dir / "snapshots" / f"{sha}.json.gz"
        if not p.exists():
            missing += 1
            continue
        raw = p.read_bytes()
        if hashlib.sha256(gzip.decompress(raw)).hexdigest() != sha:
            print(f"  ignorado (hash não confere): {p.name}")
            continue
        storage.put(storage.BUCKET_SNAPSHOTS, storage.object_key(ws, f"{sha}.json.gz"), raw, "application/gzip", ws)
        sent += 1
    print(f"Snapshots enviados: {sent}; sem arquivo local: {missing} (o de referência TSLA é recriado sozinho).")

    moved = 0
    with eng.begin() as conn:
        rows = conn.execute(select(attachments).where(attachments.c.workspace_id == ws,
                                                      attachments.c.storage == "local")).mappings().all()
        for a in rows:
            p = data_dir / "attachments" / Path(a["path"]).name
            if not p.exists():
                continue
            key = storage.object_key(ws, str(a["journal_entry_id"]), Path(a["path"]).name)
            storage.put(storage.BUCKET_ATTACHMENTS, key, p.read_bytes(), a["content_type"], ws)
            conn.execute(update(attachments).where(attachments.c.id == a["id"]).values(storage="supabase", path=key))
            moved += 1
    print(f"Imagens do diário enviadas: {moved} de {len(rows)} locais.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
