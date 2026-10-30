"""E2E backend: the public shared lab on a throwaway local SQLite database.

It first builds an "existing" lab with the demo bootstrap (strategies, journal, the reference
snapshot), then prepares it for public access with the same code as scripts/setup_public_lab.py,
and serves it in DP_AUTH_MODE=public. Used by frontend/playwright.config.ts.

    python scripts/e2e_backend.py [--port 8000] [--data-dir PATH] [--fresh]
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--data-dir", default=str(ROOT / "backend" / ".data-e2e"))
    ap.add_argument("--fresh", action="store_true")
    args = ap.parse_args()
    data = Path(args.data_dir)
    if args.fresh and data.exists():
        shutil.rmtree(data)
    os.environ.update({"DP_DATA_DIR": str(data), "DATABASE_URL": "", "DP_AUTH_MODE": "demo"})
    os.environ.setdefault("DP_RATE_LIMIT_PER_MIN", "2000")
    os.environ.setdefault("DP_RATE_LIMIT_WRITES_PER_MIN", "300")
    os.environ.setdefault("DP_RATE_LIMIT_JOBS_PER_MIN", "60")

    from app import config
    from app.auth import DEMO_WORKSPACE_ID
    from app.services.seed import bootstrap_demo
    bootstrap_demo()

    os.environ["DP_AUTH_MODE"] = "public"
    os.environ["DP_PUBLIC_WORKSPACE_ID"] = str(DEMO_WORKSPACE_ID)
    config.get_settings.cache_clear()
    from app.services.public_lab import setup_public_lab
    setup_public_lab(DEMO_WORKSPACE_ID)

    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
