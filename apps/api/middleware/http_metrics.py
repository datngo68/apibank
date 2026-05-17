"""Middleware đo p95/p99 latency cho từng route + status."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from packages.obs import metrics


class HttpMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start
        # Lấy template path để giảm cardinality (FastAPI gắn route khi match)
        route_path = getattr(request.scope.get("route"), "path", None) or request.url.path
        # Gộp asset paths để tránh nổ cardinality
        if route_path.startswith("/assets/"):
            route_path = "/assets/*"
        metrics.http_request_duration_seconds.labels(
            method=request.method,
            route=route_path,
            status=str(response.status_code),
        ).observe(elapsed)
        return response
