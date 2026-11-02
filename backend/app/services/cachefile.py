"""Disk cache helpers shared by the SEC, GDELT and House Clerk adapters (Blocos 7 to 10).

write_atomic: the bytes go to a temporary file in the same folder, then os.replace swaps it in, so a
reader never sees a half-written file (a crash or two requests writing the same key at once).
read_json: a cached JSON file that does not parse is deleted and treated as a miss, instead of
breaking the endpoint until the cache expires.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_json(path: Path):  # noqa: ANN201
    """-> the parsed JSON, or None when the cached file is unreadable (it is removed)."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        path.unlink(missing_ok=True)
        return None
