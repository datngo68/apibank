"""Tests cho notification dispatcher."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import Notification, NotificationPreference, User
from packages.notifications.dispatcher import notify
from packages.security.passwords import hash_password


@pytest.mark.asyncio
async def test_default_channels_create_in_app(initialized_db: AsyncSession) -> None:
    user = User(email="n@a.com", password_hash=hash_password("xxxxxxxx"), full_name="N")
    initialized_db.add(user)
    await initialized_db.flush()
    await notify(
        initialized_db,
        user=user,
        kind="topup_credited",
        title="Đã nạp tiền",
        body="50.000 đ",
        payload={"amount": 50_000},
    )
    await initialized_db.commit()
    rows = list(
        (
            await initialized_db.scalars(
                select(Notification)
                .where(Notification.user_id == user.id)
                .where(Notification.channel == "in_app")
            )
        ).all()
    )
    assert len(rows) == 1
    assert rows[0].kind == "topup_credited"
    assert rows[0].title == "Đã nạp tiền"
    # In-app coi như delivered ngay (UI query trực tiếp).
    assert rows[0].sent_at is not None


@pytest.mark.asyncio
async def test_outbox_email_row_pending(initialized_db: AsyncSession) -> None:
    """Email/telegram chỉ INSERT row sent_at=NULL — scheduler gửi async."""
    user = User(
        email="o@a.com",
        password_hash=hash_password("xxxxxxxx"),
        telegram_chat_id="123456",
    )
    initialized_db.add(user)
    await initialized_db.flush()
    await notify(initialized_db, user=user, kind="topup_credited", title="Hi")
    await initialized_db.commit()

    email_row = (
        await initialized_db.scalars(
            select(Notification)
            .where(Notification.user_id == user.id)
            .where(Notification.channel == "email")
        )
    ).first()
    telegram_row = (
        await initialized_db.scalars(
            select(Notification)
            .where(Notification.user_id == user.id)
            .where(Notification.channel == "telegram")
        )
    ).first()
    assert email_row is not None
    assert email_row.sent_at is None
    assert telegram_row is not None
    assert telegram_row.sent_at is None


@pytest.mark.asyncio
async def test_preference_disable_in_app(initialized_db: AsyncSession) -> None:
    user = User(email="d@a.com", password_hash=hash_password("xxxxxxxx"), full_name="D")
    initialized_db.add(user)
    await initialized_db.flush()
    initialized_db.add(
        NotificationPreference(
            user_id=user.id, kind="webhook_failing", channel="email", enabled=True
        )
    )
    await initialized_db.flush()
    await notify(initialized_db, user=user, kind="webhook_failing", title="Webhook đỏ")
    await initialized_db.commit()
    in_app_rows = list(
        (
            await initialized_db.scalars(
                select(Notification)
                .where(Notification.user_id == user.id)
                .where(Notification.channel == "in_app")
            )
        ).all()
    )
    # Pref chỉ bật email; in_app không nằm trong danh sách → không tạo
    assert in_app_rows == []
    email_rows = list(
        (
            await initialized_db.scalars(
                select(Notification)
                .where(Notification.user_id == user.id)
                .where(Notification.channel == "email")
            )
        ).all()
    )
    assert len(email_rows) == 1


@pytest.mark.asyncio
async def test_telegram_skipped_when_user_has_no_chat_id(initialized_db: AsyncSession) -> None:
    user = User(
        email="t@a.com",
        password_hash=hash_password("xxxxxxxx"),
        full_name="T",
        telegram_chat_id=None,
    )
    initialized_db.add(user)
    await initialized_db.flush()
    # Không raise dù bật tất cả channel mặc định
    await notify(
        initialized_db,
        user=user,
        kind="bank_login_failed",
        title="Đăng nhập MB lỗi",
    )
    await initialized_db.commit()
    # Không có row telegram vì user chưa link chat_id
    telegram = list(
        (
            await initialized_db.scalars(
                select(Notification)
                .where(Notification.user_id == user.id)
                .where(Notification.channel == "telegram")
            )
        ).all()
    )
    assert telegram == []


@pytest.mark.asyncio
async def test_unknown_kind_falls_back_in_app(initialized_db: AsyncSession) -> None:
    user = User(email="u@a.com", password_hash=hash_password("xxxxxxxx"))
    initialized_db.add(user)
    await initialized_db.flush()
    await notify(initialized_db, user=user, kind="custom_event", title="Hello")
    await initialized_db.commit()
    rows = list(
        (
            await initialized_db.scalars(
                select(Notification).where(Notification.kind == "custom_event")
            )
        ).all()
    )
    assert len(rows) == 1
    assert rows[0].channel == "in_app"
