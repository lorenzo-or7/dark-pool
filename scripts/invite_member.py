"""Invite a member to the DARK POOL workspace (run by the project owner only).

Uses the Supabase service role key from the environment. The key never goes
to the browser and is never typed into a chat: set it in your shell or in a
local .env that is not committed.

    # first member: creates the workspace and makes them owner
    py -3 scripts/invite_member.py --email owner@example.com --create-workspace "DARK POOL" --role owner
    # second member
    py -3 scripts/invite_member.py --email lipe@example.com --workspace-id <uuid> --role member

What it does:
  1. Sends a Supabase Auth invite e-mail (the person sets their own password),
     or reuses the account if it already exists.
  2. Creates the workspace when asked.
  3. Adds the membership row. RLS gives the member access to the workspace.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


def load_env() -> None:
    for p in (Path(__file__).resolve().parent.parent / ".env", Path(__file__).resolve().parent.parent / "backend" / ".env"):
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"'))


def call(method: str, url: str, key: str, body: dict | None = None, prefer: str | None = None) -> tuple[int, object]:
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    req = urllib.request.Request(url, method=method, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode() or "null"
            return r.status, json.loads(raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode() or "null"
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw


def find_user(base: str, key: str, email: str) -> str | None:
    page = 1
    while page < 50:
        status, data = call("GET", f"{base}/auth/v1/admin/users?page={page}&per_page=200", key)
        if status != 200:
            sys.exit(f"Não foi possível listar usuários (HTTP {status}).")
        users = data.get("users", []) if isinstance(data, dict) else []
        for u in users:
            if (u.get("email") or "").lower() == email.lower():
                return u["id"]
        if len(users) < 200:
            return None
        page += 1
    return None


def main() -> int:
    load_env()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--email", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--workspace-id")
    g.add_argument("--create-workspace", metavar="NAME")
    ap.add_argument("--role", choices=["owner", "member"], default="member")
    ap.add_argument("--redirect", default=os.environ.get("DP_SITE_URL", "http://localhost:5173") + "/reset-password")
    a = ap.parse_args()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", a.email):
        sys.exit("E-mail inválido.")
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not base or not key:
        sys.exit("Defina SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY no ambiente (nunca no frontend).")

    uid = find_user(base, key, a.email)
    if uid:
        print(f"Conta já existe: {uid}")
    else:
        status, data = call("POST", f"{base}/auth/v1/invite", key, {"email": a.email, "redirect_to": a.redirect})
        if status >= 300:
            sys.exit(f"Convite recusado (HTTP {status}): {data}")
        uid = data["id"]
        print(f"Convite enviado para {a.email} ({uid}).")

    ws = a.workspace_id
    if a.create_workspace:
        status, data = call("POST", f"{base}/rest/v1/workspaces", key, {"name": a.create_workspace},
                            prefer="return=representation")
        if status >= 300:
            sys.exit(f"Não foi possível criar o workspace (HTTP {status}): {data}")
        ws = data[0]["id"]
        print(f"Workspace criado: {ws}")
    status, data = call("POST", f"{base}/rest/v1/workspace_members", key,
                        {"workspace_id": ws, "user_id": uid, "role": a.role},
                        prefer="resolution=merge-duplicates,return=representation")
    if status >= 300:
        sys.exit(f"Não foi possível registrar o acesso (HTTP {status}): {data}")
    print(f"{a.email} agora é {a.role} do workspace {ws}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
