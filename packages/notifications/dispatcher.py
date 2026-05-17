"""Dispatcher chọn kênh gửi notification dựa trên NotificationPreference.

API:
    await notify(session, user, kind, title, body=..., payload=...)

Outbox pattern: ``notify`` chỉ ghi DB (`Notification` row mỗi channel).
Email/Telegram được gửi async qua ``dispatch_pending_notifications`` trong
scheduler — tránh chặn critical path ingest bởi SMTP/HTTP timeout.

Cần commit của caller để các row Notification visible. Caller chịu trách nhiệm
``await session.commit()`` sau khi gọi ``notify``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import Notification, NotificationPreference, User
from packages.notifications.email import send_email
from packages.notifications.in_app import create_in_app
from packages.notifications.telegram import send_telegram

logger = logging.getLogger(__name__)

DEFAULT_CHANNELS: dict[str, list[str]] = {
    "topup_credited": ["in_app", "email", "telegram"],
    "subscription_purchased": ["in_app", "email"],
    "subscription_expiring": ["in_app", "email", "telegram"],
    "subscription_expired": ["in_app", "email"],
    "webhook_failing": ["in_app", "telegram"],
    "bank_login_failed": ["in_app", "email", "telegram"],
}


async def _enabled_channels(
    session: AsyncSession, user_id: str, kind: str
) -> list[str]:
    prefs = list(
        (
            await session.scalars(
                select(NotificationPreference)
                .where(NotificationPreference.user_id == user_id)
                .where(NotificationPreference.kind == kind)
            )
        ).all()
    )
    if not prefs:
        return list(DEFAULT_CHANNELS.get(kind, ["in_app"]))
    return [p.channel for p in prefs if p.enabled]


async def notify(
    session: AsyncSession,
    *,
    user: User,
    kind: str,
    title: str,
    body: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Ghi notification vào outbox (bảng `Notification`).

    Email/Telegram chưa gửi ở đây — chỉ insert row với ``sent_at IS NULL``.
    ``dispatch_pending_notifications`` sẽ gửi async + cập nhật ``sent_at``.

    Trường hợp ``in_app``: ``sent_at = now`` ngay vì in-app vốn là ghi DB,
    user query trực tiếp không cần "delivery" thêm.
    """
    channels = await _enabled_channels(session, user.id, kind)
    now = datetime.now(UTC)
    if "in_app" in channels:
        record = await create_in_app(
            session,
            user_id=user.id,
            kind=kind,
            title=title,
            body=body,
            payload=payload,
        )
        # in_app coi như đã "delivered" ngay — UI query trực tiếp.
        record.sent_at = now
    if "email" in channels:
        session.add(
            Notification(
                user_id=user.id,
                channel="email",
                kind=kind,
                title=title,
                body=body,
                payload_json={**(payload or {}), "to": user.email},
            )
        )
    if "telegram" in channels and user.telegram_chat_id:
        session.add(
            Notification(
                user_id=user.id,
                channel="telegram",
                kind=kind,
                title=title,
                body=body,
                payload_json={
                    **(payload or {}),
                    "chat_id": user.telegram_chat_id,
                },
            )
        )


async def dispatch_pending_notifications(
    session: AsyncSession, *, batch_size: int = 100
) -> int:
    """Gửi tất cả Notification có ``sent_at IS NULL`` qua channel tương ứng.

    Trả về số notification đã gửi thành công.

    Idempotency: dùng ``sent_at`` làm flag — gửi xong thì set; nếu gửi fail
    thì không set, lần sau sẽ thử lại. Notification cũ hơn 24h và vẫn fail
    sẽ được skip ở lần thứ N (chống bão SMTP) — TODO khi cần.
    """
    rows = list(
        (
            await session.scalars(
                select(Notification)
                .where(Notification.sent_at.is_(None))
                .where(Notification.channel.in_(("email", "telegram")))
                .order_by(Notification.created_at.asc())
                .limit(batch_size)
            )
        ).all()
    )
    if not rows:
        return 0

    delivered_ids: list[str] = []
    for row in rows:
        try:
            ok = await _deliver(session, row)
        except Exception:  # noqa: BLE001
            logger.exception(
                "notification_dispatch_failed",
                extra={"id": row.id, "channel": row.channel, "kind": row.kind},
            )
            ok = False
        if ok:
            delivered_ids.append(row.id)

    if delivered_ids:
        await session.execute(
            update(Notification)
            .where(Notification.id.in_(delivered_ids))
            .values(sent_at=datetime.now(UTC))
        )
        await session.commit()
    return len(delivered_ids)


async def _deliver(session: AsyncSession, row: Notification) -> bool:
    payload = row.payload_json or {}
    if row.channel == "email":
        to_addr = payload.get("to")
        if not to_addr:
            user = await session.get(User, row.user_id)
            to_addr = user.email if user else None
        if not to_addr:
            return False
        return await send_email(
            to=to_addr,
            subject=row.title,
            body=row.body or row.title,
            session=session,
        )
    if row.channel == "telegram":
        chat_id = payload.get("chat_id")
        if not chat_id:
            user = await session.get(User, row.user_id)
            chat_id = user.telegram_chat_id if user else None
        if not chat_id:
            return False
        text = f"*{row.title}*\n{row.body or ''}"
        return await send_telegram(text, chat_id=chat_id, session=session)
    return False


__all__ = ["notify", "dispatch_pending_notifications", "DEFAULT_CHANNELS"]
