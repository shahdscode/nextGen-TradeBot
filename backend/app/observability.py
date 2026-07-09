"""
Application observability: structured logging, request logging, and a global
exception handler so unhandled errors are logged (with a correlation id and
traceback) and returned as clean JSON instead of leaking a raw stack trace.
"""
from __future__ import annotations

import logging
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings

logger = logging.getLogger("nextgen")


def setup_logging() -> None:
    level = getattr(logging, str(settings.log_level).upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    # Quiet noisy libraries.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


class RequestLogMiddleware(BaseHTTPMiddleware):
    """Log each request with a correlation id, status, and duration."""

    async def dispatch(self, request: Request, call_next):
        rid = uuid.uuid4().hex[:8]
        request.state.request_id = rid
        start = time.time()
        try:
            response = await call_next(request)
        except Exception:
            # Timing only here (no traceback) — the exception handler logs the
            # full traceback, so we avoid logging it twice.
            dur = (time.time() - start) * 1000
            logger.warning("rid=%s %s %s -> 500 (%.0fms)",
                           rid, request.method, request.url.path, dur)
            raise
        dur = (time.time() - start) * 1000
        # Only log slow or non-2xx requests at INFO; the rest at DEBUG.
        lvl = logging.INFO if (response.status_code >= 400 or dur > 1000) else logging.DEBUG
        logger.log(lvl, "rid=%s %s %s -> %s (%.0fms)",
                   rid, request.method, request.url.path, response.status_code, dur)
        response.headers["X-Request-ID"] = rid
        return response


async def unhandled_exception_handler(request: Request, exc: Exception):
    rid = getattr(request.state, "request_id", "-")
    logger.exception("rid=%s unhandled error on %s %s",
                     rid, request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": rid},
        headers={"X-Request-ID": rid},
    )


def install(app) -> None:
    """Wire logging, request-log middleware, and the global exception handler."""
    setup_logging()
    app.add_middleware(RequestLogMiddleware)
    app.add_exception_handler(Exception, unhandled_exception_handler)
