"""Dispatcher chọn kênh gửi notification dựa trên NotificationPreference.

API:
    await notify(session, user, kind, title, body=..., payload=...)

Outbox pattern: ``notify`` chỉ ghi DB (`Notification` row mỗi channel).
Email/Telegram được gửi async qua ``dispatch_pending_notifications`` trong
scheduler — tránh chặn critical path ingest bởi SMTP/HTTP timeout.

Retry/DLQ: rows có ``status='pending'`` và ``next_run_at <= now`` mới được
pick. Khi gửi fail, ``attempt`` tăng và ``next_run_at`` đẩy theo backoff
(1m, 5m, 30m, 2h, 12h). Sau ``max_attempts`` thì chuyển ``status='dead'``.

Cần commit của caller để các row Notification visible. Caller chịu trách nhiệm
``await session.commit()`` sau khi gọi ``notify``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import Notification, NotificationPreference, User
from packages.notifications.email import send_email
from packages.notifications.in_app import create_in_app
from packages.notifications.telegram import send_telegram
from packages.obs import metrics

logger = logging.getLogger(__name__)

DEFAULT_CHANNELS: dict[str, list[str]] = {
    "topup_credited": ["in_app", "email", "telegram"],
    "subscription_purchased": ["in_app", "email"],
    "subscription_expiring": ["in_app", "email", "telegram"],
    "subscription_expired": ["in_app", "email"],
    "webhook_failing": ["in_app", "telegram"],
    "bank_login_failed": ["in_app", "email", "telegram"],
}

# Exponential-ish backoff (giây): 1m, 5m, 30m, 2h, 12h.
_RETRY_DELAYS_SEC = (60, 300, 1800, 7200, 43200)
_MAX_ATTEMPTS = len(_RETRY_DELAYS_SEC)


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
        record.status = "sent"
    if "email" in channels:
        session.add(
            Notification(
                user_id=user.id,
                channel="email",
                kind=kind,
                title=title,
                body=body,
                payload_json={**(payload or {}), "to": user.email},
                status="pending",
                next_run_at=now,
                max_attempts=_MAX_ATTEMPTS,
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
                status="pending",
                next_run_at=now,
                max_attempts=_MAX_ATTEMPTS,
            )
        )


async def dispatch_pending_notifications(
    session: AsyncSession, *, batch_size: int = 100
) -> int:
    """Gửi tất cả Notification có ``status='pending'`` và due theo ``next_run_at``.

    Trả về số notification đã gửi thành công ở batch này.

    Khi gửi fail: tăng ``attempt``, đẩy ``next_run_at`` theo backoff. Sau
    ``max_attempts`` → ``status='dead'`` (DLQ, admin xử lý sau).
    """
    now = datetime.now(UTC)
    rows = list(
        (
            await session.scalars(
                select(Notification)
                .where(Notification.channel.in_(("email", "telegram")))
                .where(
                    or_(
                        Notification.status == "pending",
                        # backward compat: rows cũ chưa có status nhưng còn sent_at IS NULL.
                        Notification.status.is_(None),
                    )
                )
                .where(Notification.next_run_at <= now)
                .order_by(Notification.next_run_at.asc())
                .limit(batch_size)
            )
        ).all()
    )
    if not rows:
        return 0

    delivered = 0
    for row in rows:
        try:
            ok = await _deliver(session, row)
            err: str | None = None
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "notification_dispatch_failed",
                extra={"id": row.id, "channel": row.channel, "kind": row.kind},
            )
            ok = False
            err = f"{type(exc).__name__}: {exc}"[:500]

        if ok:
            row.status = "sent"
            row.sent_at = datetime.now(UTC)
            row.last_error = None
            metrics.notification_dispatch_total.labels(
                channel=row.channel, result="sent"
            ).inc()
            delivered += 1
        else:
            row.attempt = (row.attempt or 0) + 1
            if row.attempt >= (row.max_attempts or _MAX_ATTEMPTS):
                row.status = "dead"
                row.last_error = err or "max attempts exceeded"
                metrics.notification_dispatch_total.labels(
                    channel=row.channel, result="dead"
                ).inc()
            else:
                idx = min(row.attempt - 1, len(_RETRY_DELAYS_SEC) - 1)
                row.next_run_at = datetime.now(UTC) + timedelta(
                    seconds=_RETRY_DELAYS_SEC[idx]
                )
                row.last_error = err
                metrics.notification_dispatch_total.labels(
                    channel=row.channel, result="retry"
                ).inc()

    await session.commit()
    return delivered


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
