from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, cast

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware

from packages.config.settings import get_settings
from packages.security.rate_limit import (
    InMemoryRateLimiter,
    TokenBucketRateLimiter,
)

logger = logging.getLogger(__name__)

_REDIS_RETRY_AFTER_SECONDS = 60.0


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, *, capacity: int = 120, window_seconds: int = 60) -> None:
        super().__init__(app)
        self._capacity = capacity
        self._window_seconds = window_seconds
        self._redis: Redis | None = None
        self._limiter: TokenBucketRateLimiter | None = None
        self._fallback = InMemoryRateLimiter(
            capacity=capacity, window_seconds=window_seconds
        )
        self._unavailable_until: float = 0.0

    async def _get_limiter(self) -> TokenBucketRateLimiter | InMemoryRateLimiter:
        if self._limiter is not None:
            return self._limiter
        # Nếu vừa fail Redis → fallback in-memory cho tới khi hết thời gian retry.
        if self._unavailable_until > time.monotonic():
            return self._fallback
        try:
            self._redis = Redis.from_url(get_settings().redis_url)
            await cast(Awaitable[Any], self._redis.ping())
        except Exception as exc:  # noqa: BLE001
            logger.warning("rate_limit_redis_unavailable: %s", exc)
            self._unavailable_until = time.monotonic() + _REDIS_RETRY_AFTER_SECONDS
            return self._fallback
        self._limiter = TokenBucketRateLimiter(
            redis=self._redis,
            capacity=self._capacity,
            window_seconds=self._window_seconds,
        )
        return self._limiter

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path
        if path.startswith("/healthz") or path.startswith("/readyz") or path.startswith("/metrics"):
            return await call_next(request)
        # SSE long-lived endpoints — bypass rate limit
        if path.endswith("/events") and "/topup/" in path:
            return await call_next(request)
        if path.startswith("/api/v1/telegram/webhook"):
            # Telegram phải gọi liên tục, đã verify bằng secret_token header
            return await call_next(request)

        limiter = await self._get_limiter()

        host = request.client.host if request.client else "anon"
        identifier = request.headers.get("authorization") or host
        decision = await limiter.hit(identifier)
        if not decision.allowed:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "rate limit exceeded"},
                headers={"Retry-After": str(int(decision.retry_after_seconds))},
            )
        return await call_next(request)
