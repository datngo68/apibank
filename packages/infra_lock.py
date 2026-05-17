from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

from redis.asyncio import Redis


@asynccontextmanager
async def redis_lock(redis: Redis, key: str, *, ttl_seconds: int) -> AsyncIterator[bool]:
    acquired = cast(Any, await redis.set(key, "1", ex=ttl_seconds, nx=True))
    try:
        yield bool(acquired)
    finally:
        if acquired:
            await redis.delete(key)
