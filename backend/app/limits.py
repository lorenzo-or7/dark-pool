"""Server-side request limits for the public endpoints. Buttons that disable themselves are a
convenience; these are the actual limits. In memory, per process: the shared lab runs as a
single backend instance.

Client address: the socket peer, unless DP_TRUSTED_PROXY_HOPS > 0 (behind a hosting proxy that
appends the visitor's address to X-Forwarded-For). Then the entry that many hops from the
right is used; entries further left are written by the client and are never trusted."""

from __future__ import annotations

import ipaddress
import threading
import time
from collections import deque
from contextvars import ContextVar

from fastapi import Request
from fastapi.responses import JSONResponse

from .config import get_settings

WINDOW_S = 60.0
# Requests that start background work (engines, downloads).
JOB_PATHS = ("/api/timemachine", "/api/backtests", "/api/scans", "/api/universe/refresh")
UPLOAD_SUFFIX = "/attachments"
# Reads that reach external providers or engine subprocesses.
HEAVY_PREFIXES = ("/api/quotes", "/api/assets/")
HEAVY_SUFFIXES = ("/news", "/fundamentals", "/chart")

# The current request's client key, for limits applied deeper in the code (jobs per client).
current_client: ContextVar[str] = ContextVar("dp_client", default="unknown")


class SlidingWindow:
    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, bucket: str, client: str, limit: int) -> float | None:
        """Record a hit. -> None when allowed, else seconds until the next slot frees up."""
        if limit <= 0:
            return None
        t = time.monotonic()
        key = (bucket, client)
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and t - q[0] >= WINDOW_S:
                q.popleft()
            if len(q) >= limit:
                return max(1.0, WINDOW_S - (t - q[0]))
            q.append(t)
            if len(self._hits) > 20000:  # forget idle clients
                for k in [k for k, v in self._hits.items() if not v or t - v[-1] >= WINDOW_S][:10000]:
                    self._hits.pop(k, None)
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


windows = SlidingWindow()


def _too_many(retry: float, message: str) -> JSONResponse:
    return JSONResponse({"detail": {"code": "rate_limited", "message": message}}, status_code=429,
                        headers={"Retry-After": str(int(retry) + 1)})


def _bucket(addr: str) -> str:
    """IPv6 clients get a whole /64 (one subscriber), so rotating addresses does not help."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return addr
    if ip.version == 6:
        if ip.ipv4_mapped:
            return str(ip.ipv4_mapped)
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    hops = get_settings().dp_trusted_proxy_hops
    if hops <= 0:
        return _bucket(peer)
    chain = [x.strip() for x in request.headers.get("x-forwarded-for", "").split(",") if x.strip()]
    return _bucket(chain[-hops] if len(chain) >= hops else peer)


def check(request: Request) -> JSONResponse | None:
    """-> a 413/429 response, or None to let the request through."""
    s = get_settings()
    path = request.url.path
    if not path.startswith("/api/") or path == "/api/health" or request.method == "OPTIONS":
        return None
    method = request.method.upper()

    # Payload size: declared length first (the server never reads a body above the limit).
    is_upload = method == "POST" and path.endswith(UPLOAD_SUFFIX)
    max_bytes = s.dp_max_upload_bytes + 64 * 1024 if is_upload else s.dp_max_body_bytes
    length = request.headers.get("content-length")
    if length is not None:
        try:
            if int(length) > max_bytes:
                return JSONResponse({"detail": {"code": "too_large",
                                                "message": "A requisição excede o tamanho máximo aceito."}},
                                    status_code=413)
        except ValueError:
            return JSONResponse({"detail": {"code": "bad_request", "message": "Content-Length inválido."}},
                                status_code=400)
    elif method in ("POST", "PUT", "PATCH") and request.headers.get("transfer-encoding"):
        return JSONResponse({"detail": {"code": "length_required",
                                        "message": "Envie o corpo com Content-Length."}}, status_code=411)

    client = client_ip(request)
    current_client.set(client)
    retry = windows.hit("all", client, s.dp_rate_limit_per_min)
    if retry:
        return _too_many(retry, "Muitas requisições em pouco tempo. Aguarde alguns segundos.")
    heavy_get = method == "GET" and path.startswith(HEAVY_PREFIXES) and (
        path == "/api/quotes" or path.endswith(HEAVY_SUFFIXES))
    # The ORB plan downloads the day's bars when no snapshot is given.
    if heavy_get or (method == "POST" and path == "/api/plan/orb"):
        retry = windows.hit("heavy", client, s.dp_rate_limit_heavy_per_min)
        if retry:
            return _too_many(retry, "Muitas consultas de mercado em pouco tempo. Aguarde alguns segundos.")
    if method in ("POST", "PUT", "PATCH", "DELETE"):
        retry = windows.hit("write", client, s.dp_rate_limit_writes_per_min)
        if retry:
            return _too_many(retry, "Muitas alterações em pouco tempo. Aguarde alguns segundos.")
        if method == "POST" and path in JOB_PATHS:
            retry = windows.hit("job", client, s.dp_rate_limit_jobs_per_min)
            if retry:
                return _too_many(retry, "Muitas execuções iniciadas em pouco tempo. Aguarde um minuto.")
    return None
