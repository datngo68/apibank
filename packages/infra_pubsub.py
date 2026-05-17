"""Redis pub/sub helpers cho realtime event (topup paid, webhook kick).

Thiết kế best-effort:

- Nếu Redis unavailable, mọi thao tác là no-op (không raise lên caller).
  Người gọi nên có fallback (poll DB, APScheduler safety net) để đảm bảo
  không phụ thuộc duy nhất vào kênh này.
- Singleton client cho publisher để tránh handshake mới mỗi lần publish.
- Subscriber dùng context manager riêng vì cần `pubsub` connection riêng
  (Redis không share connection giữa publish/subscribe).

Channel naming:

- ``topup:paid:{order_id}`` — publish khi 1 topup order chuyển sang paid;
  payload là JSON ``{"order_id": ..., "code": ...}``. Subscriber: SSE topup.
- ``webhook:kick`` — publish khi có WebhookAttempt mới đăng ký; payload rỗng.
  Subscriber: scheduler webhook dispatcher.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

from redis.asyncio import Redis

from packages.config.settings import get_settings

logger = logging.getLogger(__name__)

_publisher: Redis | None = None
_publisher_unavailable: bool = False


async def _get_publisher() -> Redis | None:
    """Lazy singleton publisher client. Cache `unavailable` để không spam ping."""
    global _publisher, _publisher_unavailable
    if _publisher_unavailable:
        return None
    if _publisher is not None:
        return _publisher
    try:
        client = Redis.from_url(get_settings().redis_url)
        await client.ping()
    except Exception as exc:  # noqa: BLE001
        logger.warning("redis_pubsub_unavailable: %s", exc)
        _publisher_unavailable = True
        return None
    _publisher = client
    return client


async def reset_for_tests() -> None:
    """Reset singleton — gọi từ fixture test khi đổi settings."""
    global _publisher, _publisher_unavailable
    if _publisher is not None:
        with suppress(Exception):
            await _publisher.aclose()
    _publisher = None
    _publisher_unavailable = False


async def publish_json(channel: str, payload: dict[str, Any]) -> None:
    """Best-effort publish 1 message JSON. Không raise."""
    client = await _get_publisher()
    if client is None:
        return
    try:
        await client.publish(channel, json.dumps(payload, separators=(",", ":")))
    except Exception:  # noqa: BLE001
        logger.warning("redis_publish_failed", extra={"channel": channel})


async def publish(channel: str, message: str = "") -> None:
    """Best-effort publish 1 message string. Không raise."""
    client = await _get_publisher()
    if client is None:
        return
    try:
        await client.publish(channel, message)
    except Exception:  # noqa: BLE001
        logger.warning("redis_publish_failed", extra={"channel": channel})


@asynccontextmanager
async def subscribe(channel: str) -> AsyncIterator[Any]:
    """Mở 1 PubSub connection riêng cho 1 channel.

    Yield ra ``pubsub`` (hoặc ``None`` nếu Redis unavailable). Caller dùng:

        async with subscribe("topup:paid:ord_xxx") as pubsub:
            if pubsub is None:
                ...  # fallback path
            else:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
    """
    settings = get_settings()
    client: Redis | None
    try:
        client = Redis.from_url(settings.redis_url)
        await client.ping()
    except Exception as exc:  # noqa: BLE001
        logger.warning("redis_subscribe_unavailable: %s", exc)
        yield None
        return

    pubsub = client.pubsub()
    try:
        await pubsub.subscribe(channel)
        yield pubsub
    finally:
        with suppress(Exception):
            await pubsub.unsubscribe(channel)
        with suppress(Exception):
            await pubsub.aclose()
        with suppress(Exception):
            await client.aclose()


async def wait_for_message(
    pubsub: Any, *, timeout: float
) -> dict[str, Any] | None:
    """Block tối đa ``timeout`` giây, trả về message dict hoặc None.

    Trả None khi timeout, khi message là subscribe-confirm, hoặc khi pubsub None.
    """
    if pubsub is None:
        await asyncio.sleep(timeout)
        return None
    try:
        msg = await pubsub.get_message(
            ignore_subscribe_messages=True, timeout=timeout
        )
    except Exception:  # noqa: BLE001
        return None
    if msg is None:
        return None
    if msg.get("type") not in {"message", "pmessage"}:
        return None
    return msg


__all__ = [
    "publish",
    "publish_json",
    "subscribe",
    "wait_for_message",
    "reset_for_tests",
]
