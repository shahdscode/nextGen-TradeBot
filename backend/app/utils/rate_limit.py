"""
Lightweight in-memory rate limiting (no external dependency).

A sliding-window counter keyed by (route, client IP). Used to throttle abuse on
auth endpoints (brute-force logins, registration spam, reset-token guessing).

Note: state is per-process. With multiple workers each enforces the limit
independently, so effective limits scale with worker count — adequate for a
small beta. For strict global limits, back this with Redis later.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

_lock = threading.Lock()
_hits: dict[str, deque] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    # Honor a reverse-proxy forwarded header (Caddy/Nginx) when present.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(max_calls: int, window_seconds: int):
    """
    FastAPI dependency factory. Allows up to `max_calls` per `window_seconds`
    per client IP per route; otherwise raises HTTP 429 with Retry-After.
    """
    def dependency(request: Request) -> None:
        key = f"{request.url.path}:{_client_ip(request)}"
        now = time.time()
        with _lock:
            dq = _hits[key]
            cutoff = now - window_seconds
            while dq and dq[0] <= cutoff:
                dq.popleft()
            if len(dq) >= max_calls:
                retry = int(window_seconds - (now - dq[0])) + 1
                raise HTTPException(
                    status_code=429,
                    detail=f"Too many requests. Try again in {retry}s.",
                    headers={"Retry-After": str(retry)},
                )
            dq.append(now)
    return dependency
