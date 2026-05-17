"""Phase 5: notification outbox dispatcher pickup pending rows."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import Notification, User
from packages.notifications.dispatcher import (
    dispatch_pending_notifications,
    notify,
)
from packages.security.passwords import hash_password


@pytest.mark.asyncio
async def test_dispatch_pending_marks_sent_when_email_succeeds(
    initialized_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = User(
        email="dispatch@a.com",
        password_hash=hash_password("xxxxxxxx"),
        telegram_chat_id="42",
    )
    initialized_db.add(user)
    await initialized_db.flush()
    await notify(initialized_db, user=user, kind="topup_credited", title="Hi")
    await initialized_db.commit()

    sent_emails: list[str] = []

    async def fake_send_email(**kwargs):  # type: ignore[no-untyped-def]
        sent_emails.append(kwargs.get("to", ""))
        return True

    async def fake_send_telegram(text, **kwargs):  # type: ignore[no-untyped-def]
        return True

    monkeypatch.setattr(
        "packages.notifications.dispatcher.send_email", fake_send_email
    )
    monkeypatch.setattr(
        "packages.notifications.dispatcher.send_telegram", fake_send_telegram
    )

    sent = await dispatch_pending_notifications(initialized_db)
    assert sent >= 1

    rows = list(
        (
            await initialized_db.scalars(
                select(Notification)
                .where(Notification.user_id == user.id)
                .where(Notification.channel.in_(("email", "telegram")))
            )
        ).all()
    )
    assert all(r.sent_at is not None for r in rows)
    assert "dispatch@a.com" in sent_emails


@pytest.mark.asyncio
async def test_dispatch_pending_keeps_pending_when_send_fails(
    initialized_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = User(email="retry@a.com", password_hash=hash_password("xxxxxxxx"))
    initialized_db.add(user)
    await initialized_db.flush()
    await notify(
        initialized_db, user=user, kind="subscription_expired", title="Hết hạn"
    )
    await initialized_db.commit()

    async def failing_send_email(**kwargs):  # type: ignore[no-untyped-def]
        return False

    monkeypatch.setattr(
        "packages.notifications.dispatcher.send_email", failing_send_email
    )

    sent = await dispatch_pending_notifications(initialized_db)
    assert sent == 0
    row = (
        await initialized_db.scalars(
            select(Notification)
            .where(Notification.user_id == user.id)
            .where(Notification.channel == "email")
        )
    ).first()
    assert row is not None
    assert row.sent_at is None
