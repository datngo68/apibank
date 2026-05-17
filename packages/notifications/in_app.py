"""In-app notification — ghi vào bảng `notifications`.

Dùng cho UI hiển thị notification bell + SSE realtime.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import Notification


async def create_in_app(
    session: AsyncSession,
    *,
    user_id: str,
    kind: str,
    title: str,
    body: str | None = None,
    payload: dict[str, Any] | None = None,
) -> Notification:
    record = Notification(
        user_id=user_id,
        channel="in_app",
        kind=kind,
        title=title,
        body=body,
        payload_json=payload or {},
    )
    session.add(record)
    await session.flush()
    return record
