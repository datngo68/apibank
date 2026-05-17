"""Quota tracker — đếm số lần gọi API theo ngày/tháng cho mỗi user.

Backend ưu tiên Redis (atomic INCR + EXPIRE); fallback in-memory cho dev.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, cast

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QuotaStatus:
    used_today: int
    used_month: int
    limit_day: int
    limit_month: int

    @property
    def exceeded(self) -> bool:
        if self.limit_day and self.used_today > self.limit_day:
            return True
        if self.limit_month and self.used_month > self.limit_month:
            return True
        return False


class QuotaTracker:
    """Đếm theo bucket day + month. Key: `quota:{user_id}:{day|month}:{bucket}`.

    Khi Redis không khả dụng, fallback in-memory.
    """

    def __init__(self, redis_url: str | None = None) -> None:
        self._redis_url = redis_url
        self._redis: Redis | None = None
        self._fallback: dict[str, int] = defaultdict(int)
        self._fallback_lock = threading.Lock()
        self._tested = False

    async def _get_redis(self) -> Redis | None:
        if self._tested:
            return self._redis
        self._tested = True
        if not self._redis_url:
            return None
        try:
            self._redis = Redis.from_url(self._redis_url)
            await cast(Awaitable[Any], self._redis.ping())
        except Exception:  # noqa: BLE001
            logger.warning("quota_redis_unavailable")
            self._redis = None
        return self._redis

    async def hit(
        self, user_id: str, *, limit_day: int = 0, limit_month: int = 0
    ) -> QuotaStatus:
        now = int(time.time())
        day_bucket = now // 86_400
        month_bucket = now // (86_400 * 30)
        day_key = f"quota:{user_id}:day:{day_bucket}"
        month_key = f"quota:{user_id}:month:{month_bucket}"

        redis = await self._get_redis()
        if redis is not None:
            day_count = int(await cast(Awaitable[Any], redis.incr(day_key)))
            if day_count == 1:
                await cast(Awaitable[Any], redis.expire(day_key, 86_400 + 60))
            month_count = int(await cast(Awaitable[Any], redis.incr(month_key)))
            if month_count == 1:
                await cast(Awaitable[Any], redis.expire(month_key, 86_400 * 31))
        else:
            with self._fallback_lock:
                self._fallback[day_key] += 1
                self._fallback[month_key] += 1
                day_count = self._fallback[day_key]
                month_count = self._fallback[month_key]

        return QuotaStatus(
            used_today=day_count,
            used_month=month_count,
            limit_day=limit_day,
            limit_month=limit_month,
        )

    async def reset(self, user_id: str) -> None:
        redis = await self._get_redis()
        if redis is not None:
            keys = [k async for k in redis.scan_iter(match=f"quota:{user_id}:*")]
            if keys:
                await cast(Awaitable[Any], redis.delete(*keys))
        else:
            with self._fallback_lock:
                for key in list(self._fallback):
                    if key.startswith(f"quota:{user_id}:"):
                        del self._fallback[key]


_singleton: QuotaTracker | None = None


def get_quota_tracker() -> QuotaTracker:
    global _singleton
    if _singleton is None:
        from packages.config.settings import get_settings

        _singleton = QuotaTracker(get_settings().redis_url)
    return _singleton


def reset_quota_singleton() -> None:
    """For tests."""
    global _singleton
    _singleton = None
