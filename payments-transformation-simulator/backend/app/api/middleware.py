"""Request middleware: correlation context, timing and a simple rate limit."""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.core.config import settings
from app.core.identifiers import request_id as new_request_id
from app.core.logging import (
    correlation_id_var,
    get_logger,
    payment_id_var,
    request_id_var,
)

logger = get_logger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Stamp a request id, propagate any inbound correlation id, and log timing."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rid = request.headers.get("x-request-id") or new_request_id()
        token_rid = request_id_var.set(rid)
        token_corr = correlation_id_var.set(request.headers.get("x-correlation-id"))
        token_pid = payment_id_var.set(None)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            request_id_var.reset(token_rid)
            correlation_id_var.reset(token_corr)
            payment_id_var.reset(token_pid)
        response.headers["x-request-id"] = rid
        logger.info(
            "request completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
                "request_id": rid,
            },
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window per-client limit.

    Deliberately simple and in-process: it protects a local demo from a runaway
    client without pretending to be production rate limiting, which belongs at
    the gateway.
    """

    def __init__(self, app) -> None:  # noqa: ANN001
        super().__init__(app)
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not settings.RATE_LIMIT_ENABLED or request.method == "OPTIONS":
            return await call_next(request)
        client = request.client.host if request.client else "unknown"
        window = settings.RATE_LIMIT_WINDOW_SECONDS
        now = time.monotonic()
        bucket = self._hits[client]
        while bucket and now - bucket[0] > window:
            bucket.popleft()
        if len(bucket) >= settings.RATE_LIMIT_REQUESTS:
            retry_after = max(1, int(window - (now - bucket[0])))
            logger.warning("rate limit exceeded", extra={"client": client})
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": (
                            f"More than {settings.RATE_LIMIT_REQUESTS} requests in "
                            f"{window}s. Retry in {retry_after}s."
                        ),
                        "requestId": request_id_var.get(),
                    }
                },
                headers={"retry-after": str(retry_after)},
            )
        bucket.append(now)
        return await call_next(request)
