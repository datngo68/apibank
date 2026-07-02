"""SSE endpoint cho topup status — push event 'paid'/'expired' realtime.

Cơ chế:

- Nếu Redis có sẵn → subscribe channel ``topup:paid:{order_id}`` và yield
  event ngay khi ingest publish (latency ~50-200ms).
- Nếu Redis unavailable → fallback poll DB 2s/connection (cách cũ).
- Bất kể đường nào, vẫn có safety poll 30s phòng miss message do reconnect.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import BankAccount, Order, User
from packages.db.session import get_session, get_sessionmaker
from packages.infra_pubsub import subscribe, wait_for_message
from packages.security.user_auth import current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/me/topup", tags=["topup-stream"], include_in_schema=False)

POLL_FALLBACK_SEC = 2.0       # Khi Redis unavailable
POLL_SAFETY_SEC = 0.5         # Khi đã subscribe Redis (an toàn miss message/race test)
PUBSUB_WAIT_SEC = 1.0         # Block 1s mỗi vòng để cho phép check disconnect
HEARTBEAT_INTERVAL_SEC = 15.0
MAX_DURATION_SEC = 30 * 60    # 30 phút
# Cap SSE concurrent per-user để tránh mở quá nhiều tab → exhaust loop slot.
MAX_CONCURRENT_PER_USER = 3
_active_streams: dict[str, int] = {}
_user_stream_lock = asyncio.Lock()


@router.get("/{code}/events")
async def topup_events(
    code: str,
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    code = code.upper()
    order = (
        await session.scalars(select(Order).where(Order.code == code))
    ).first()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")

    bank = await session.get(BankAccount, order.bank_account_id)
    if bank is None or not bank.is_system_account:
        # Topup phải gắn system bank
        raise HTTPException(status_code=403, detail="not a topup order")

    # Verify user là chủ topup (lưu user_id trong metadata_json hoặc customer_ref)
    metadata = order.metadata_json or {}
    owner_id = metadata.get("user_id") or order.user_id
    owner_email = order.customer_ref
    if owner_id and owner_id != user.id and owner_email != user.email:
        raise HTTPException(status_code=403, detail="forbidden")

    # Cap concurrent stream per user.
    async with _user_stream_lock:
        active = _active_streams.get(user.id, 0)
        if active >= MAX_CONCURRENT_PER_USER:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="too many concurrent SSE connections; close other tabs",
            )
        _active_streams[user.id] = active + 1

    sessionmaker = get_sessionmaker()
    order_id = order.id

    async def stream() -> AsyncGenerator[bytes, None]:
        start = datetime.now(UTC)
        last_heartbeat = start
        last_status = order.status
        last_db_check = start

        async def fetch_status_and_emit() -> tuple[bytes | None, bool]:
            """Đọc DB, so sánh status. Trả ``(event_bytes, is_terminal)``."""
            nonlocal last_status, last_db_check
            async with sessionmaker() as ses:
                fresh = await ses.get(Order, order_id)
                if fresh is None:
                    return _sse_event("error", {"detail": "order missing"}), True
                new_status = fresh.status
                last_db_check = datetime.now(UTC)
                if new_status == last_status:
                    return None, False
                last_status = new_status
                if new_status == "paid":
                    owner = await ses.get(User, owner_id) if owner_id else None
                    balance = (
                        int(owner.balance_vnd) if owner is not None else None
                    )
                    return (
                        _sse_event(
                            "paid",
                            {
                                "status": "paid",
                                "balance_vnd": balance,
                                "paid_at": fresh.paid_at.isoformat()
                                if fresh.paid_at
                                else None,
                            },
                        ),
                        True,
                    )
                if new_status in ("expired", "canceled"):
                    return _sse_event("expired", {"status": new_status}), True
                return _sse_event("status", {"status": new_status}), False

        try:
            yield _sse_event("hello", {"status": last_status})

            async with subscribe(f"topup:paid:{order_id}") as pubsub:
                use_pubsub = pubsub is not None
                # Initial check: order có thể đã paid trước khi client connect.
                event, terminal = await fetch_status_and_emit()
                if event is not None:
                    yield event
                if terminal:
                    return

                while True:
                    if await request.is_disconnected():
                        return

                    if use_pubsub:
                        msg = await wait_for_message(
                            pubsub, timeout=PUBSUB_WAIT_SEC
                        )
                        if msg is not None:
                            event, terminal = await fetch_status_and_emit()
                            if event is not None:
                                yield event
                            if terminal:
                                return
                    else:
                        await asyncio.sleep(POLL_FALLBACK_SEC)

                    now = datetime.now(UTC)
                    # Safety re-poll (kể cả khi pubsub đang work) — chống miss
                    # message do Redis reconnect, race subscribe-trước-publish.
                    safety_interval = (
                        POLL_SAFETY_SEC if use_pubsub else POLL_FALLBACK_SEC
                    )
                    if (now - last_db_check).total_seconds() >= safety_interval:
                        event, terminal = await fetch_status_and_emit()
                        if event is not None:
                            yield event
                        if terminal:
                            return

                    if (now - last_heartbeat).total_seconds() >= HEARTBEAT_INTERVAL_SEC:
                        last_heartbeat = now
                        yield b": ping\n\n"
                    if (now - start).total_seconds() >= MAX_DURATION_SEC:
                        yield _sse_event("timeout", {"status": last_status})
                        return
        except asyncio.CancelledError:
            return
        finally:
            async with _user_stream_lock:
                cur = _active_streams.get(user.id, 0)
                if cur <= 1:
                    _active_streams.pop(user.id, None)
                else:
                    _active_streams[user.id] = cur - 1

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


def _sse_event(event: str, data: dict[str, object]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()
