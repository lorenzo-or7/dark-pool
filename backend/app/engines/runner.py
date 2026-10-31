"""Runs the vendored Day Trader Skill scripts safely.

- Subprocesses get an argument list (never a shell string), the interpreter in
  isolated mode (-I), a private working directory, a timeout and a cancel hook.
- `load_module` imports a script for direct, pure-function calls.
trader-broker is not vendored and cannot be loaded.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import ModuleType

from ..config import get_settings

SCRIPTS = {
    "scanner": ("trader-scanner", "scan"),
    "timemachine": ("trader-timemachine", "timemachine"),
    "entry": ("trader-entry", "entry"),
    "exit": ("trader-exit", "exit"),
    "budget": ("trader-budget", "size"),
    "risk": ("trader-risk", "check"),
    "news": ("trader-news", "news"),
    "analyst": ("trader-analyst", "facts"),
    "alerts": ("trader-alerts", "alerts"),
}


class EngineError(Exception):
    """A script refused or failed; the message is the script's own plain line."""


class EngineCancelled(Exception):
    pass


class EngineTimeout(Exception):
    pass


@dataclass
class EngineResult:
    returncode: int
    stdout: str
    stderr: str


def script_path(name: str) -> Path:
    if name not in SCRIPTS:
        raise ValueError(f"unknown engine {name!r}")
    folder, mod = SCRIPTS[name]
    p = get_settings().dp_skill_dir / folder / f"{mod}.py"
    if not p.is_file():
        raise EngineError(f"engine script not found: {p}")
    return p


@lru_cache
def load_module(name: str) -> ModuleType:
    p = script_path(name)
    spec = importlib.util.spec_from_file_location(f"dp_engine_{name}", p)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_script(name: str, args: list[str], cwd: Path, timeout_s: float | None = None,
               cancelled: Callable[[], bool] | None = None, on_line: Callable[[str], None] | None = None,
               env_extra: dict[str, str] | None = None) -> EngineResult:
    if any(not isinstance(a, str) for a in args):
        raise TypeError("engine arguments must be strings")
    timeout_s = timeout_s or get_settings().dp_job_timeout_s
    cwd.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USERPROFILE")}
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(env_extra or {})
    cmd = [sys.executable, "-I", str(script_path(name)), *args]
    proc = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                            text=True, encoding="utf-8", errors="replace", shell=False)
    err_lines: list[str] = []

    def pump_err() -> None:
        assert proc.stderr
        for line in proc.stderr:
            err_lines.append(line)
            if on_line:
                on_line(line.rstrip())

    t = threading.Thread(target=pump_err, daemon=True)
    t.start()
    out_chunks: list[str] = []

    def pump_out() -> None:
        assert proc.stdout
        out_chunks.append(proc.stdout.read())

    t2 = threading.Thread(target=pump_out, daemon=True)
    t2.start()
    deadline = time.monotonic() + timeout_s
    while proc.poll() is None:
        if cancelled and cancelled():
            proc.kill()
            proc.wait()
            raise EngineCancelled()
        if time.monotonic() > deadline:
            proc.kill()
            proc.wait()
            raise EngineTimeout(f"{name} passou do limite de {int(timeout_s)} s")
        time.sleep(0.2)
    t.join(2)
    t2.join(2)
    return EngineResult(proc.returncode, "".join(out_chunks), "".join(err_lines))


def last_error_line(res: EngineResult) -> str:
    for text in (res.stderr, res.stdout):
        lines = [x.strip() for x in text.strip().splitlines() if x.strip()]
        if lines:
            line = lines[-1]
            for prefix in ("scan.py:", "timemachine.py:", "news.py:", "facts.py:"):
                if line.startswith(prefix):
                    line = line[len(prefix):].strip()
            return line
    return f"o motor terminou com código {res.returncode}"
