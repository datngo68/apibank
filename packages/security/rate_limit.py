"""Rate-limit primitives.

Hai backend song song:
- ``TokenBucketRateLimiter`` (Redis) cho production.
- ``InMemoryRateLimiter`` cho dev/test/khi Redis down (mỗi process tự đếm).

Cả hai có cùng interface ``async def hit(identifier) -> RateLimitDecision``.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass

from redis.asyncio import Redis


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: float


class TokenBucketRateLimiter:
    """Simple token-bucket using Redis with INCR + EXPIRE per fixed window."""

    def __init__(self, *, redis: Redis, capacity: int, window_seconds: int) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._redis = redis
        self._capacity = capacity
        self._window_seconds = window_seconds

    async def hit(self, identifier: str) -> RateLimitDecision:
        bucket = int(time.time()) // self._window_seconds
        key = f"ratelimit:{identifier}:{bucket}"
        current = await self._redis.incr(key)
        if current == 1:
            await self._redis.expire(key, self._window_seconds + 1)
        remaining = max(0, self._capacity - int(current))
        retry_after = 0.0 if int(current) <= self._capacity else float(self._window_seconds)
        return RateLimitDecision(
            allowed=int(current) <= self._capacity,
            remaining=remaining,
            retry_after_seconds=retry_after,
        )


class InMemoryRateLimiter:
    """Per-process fallback khi Redis không khả dụng.

    KHÔNG share giữa worker → ở multi-process production sẽ "rò" gấp số worker
    lần. Dùng tốt cho dev/test và như phòng tuyến tạm khi Redis down.
    """

    def __init__(self, *, capacity: int, window_seconds: int) -> None:
        self._capacity = capacity
        self._window_seconds = window_seconds
        self._counters: dict[tuple[str, int], int] = defaultdict(int)
        self._lock = asyncio.Lock()

    async def hit(self, identifier: str) -> RateLimitDecision:
        bucket = int(time.time()) // self._window_seconds
        async with self._lock:
            # Dọn các bucket cũ để map không phình.
            for (ident, b) in list(self._counters.keys()):
                if b < bucket - 1:
                    self._counters.pop((ident, b), None)
            self._counters[(identifier, bucket)] += 1
            current = self._counters[(identifier, bucket)]
        remaining = max(0, self._capacity - current)
        retry_after = 0.0 if current <= self._capacity else float(self._window_seconds)
        return RateLimitDecision(
            allowed=current <= self._capacity,
            remaining=remaining,
            retry_after_seconds=retry_after,
        )


__all__ = [
    "RateLimitDecision",
    "TokenBucketRateLimiter",
    "InMemoryRateLimiter",
]
