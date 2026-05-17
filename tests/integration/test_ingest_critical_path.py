"""Phase 5 verification: ingest critical path không phụ thuộc SMTP/Telegram.

Mục tiêu:
- Mock ``send_email``/``send_telegram`` raise exception → ingest vẫn commit ok,
  user vẫn được credit ví, transaction vẫn matched.
- Đảm bảo notification chỉ ghi outbox (sent_at IS NULL với email/telegram).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.banks.base import BankTransaction
from packages.billing import topup as topup_pkg
from packages.core.ingest import ingest_transaction
from packages.db.models import BankAccount, Notification, User
from packages.security.passwords import hash_password


async def _make_user(session: AsyncSession) -> User:
    user = User(
        email="ingest-fast@a.com",
        password_hash=hash_password("xxxxxxxx"),
        telegram_chat_id="999",
    )
    session.add(user)
    await session.flush()
    return user


async def _make_system_bank(session: AsyncSession) -> BankAccount:
    bank = BankAccount(
        bank_code="MB",
        account_no="0011223344",
        account_holder="APIBANK",
        credentials_enc="x",
        status="active",
        polling_enabled=True,
        is_system_account=True,
    )
    session.add(bank)
    await session.flush()
    return bank


@pytest.mark.asyncio
async def test_ingest_does_not_call_telegram_synchronously(
    initialized_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Telegram fail phải không kéo ingest fail."""
    user = await _make_user(initialized_db)
    bank = await _make_system_bank(initialized_db)
    order = await topup_pkg.create_topup_order(
        initialized_db, user=user, amount_vnd=100_000
    )
    await initialized_db.commit()

    telegram_calls: list[str] = []

    async def fail_telegram(*args, **kwargs):  # type: ignore[no-untyped-def]
        telegram_calls.append("called")
        raise RuntimeError("telegram down")

    async def fail_email(*args, **kwargs):  # type: ignore[no-untyped-def]
        telegram_calls.append("email_called")
        raise RuntimeError("smtp down")

    # Patch các channel "thực sự gửi" — nếu ingest gọi đồng bộ sẽ raise.
    monkeypatch.setattr(
        "packages.notifications.dispatcher.send_telegram", fail_telegram
    )
    monkeypatch.setattr(
        "packages.notifications.dispatcher.send_email", fail_email
    )

    bank_tx = BankTransaction(
        bank_ref_no="REF-FAST-001",
        amount=Decimal(100_000),
        content=f"NAP {order.code}",
        posted_at=datetime.now(UTC),
        counter_account=None,
        counter_name=None,
        raw={},
    )
    # Phải KHÔNG raise — ingest chỉ ghi outbox.
    await ingest_transaction(
        initialized_db, bank_account_id=bank.id, bank_transaction=bank_tx
    )

    assert telegram_calls == [], (
        "ingest không được gọi send_telegram/send_email trực tiếp; "
        "outbox dispatcher mới gửi async"
    )

    refreshed = await initialized_db.get(User, user.id)
    assert refreshed is not None
    assert Decimal(refreshed.balance_vnd) == Decimal(100_000)


@pytest.mark.asyncio
async def test_ingest_writes_notification_outbox_rows(
    initialized_db: AsyncSession,
) -> None:
    """Sau ingest paid, có ít nhất 1 row email outbox với sent_at=NULL."""
    user = await _make_user(initialized_db)
    bank = await _make_system_bank(initialized_db)
    order = await topup_pkg.create_topup_order(
        initialized_db, user=user, amount_vnd=50_000
    )
    await initialized_db.commit()

    bank_tx = BankTransaction(
        bank_ref_no="REF-OUT-001",
        amount=Decimal(50_000),
        content=order.code,
        posted_at=datetime.now(UTC),
        counter_account=None,
        counter_name=None,
        raw={},
    )
    await ingest_transaction(
        initialized_db, bank_account_id=bank.id, bank_transaction=bank_tx
    )

    rows = list(
        (
            await initialized_db.scalars(
                select(Notification).where(Notification.user_id == user.id)
            )
        ).all()
    )
    assert any(r.channel == "email" and r.sent_at is None for r in rows), (
        "phải có email outbox row pending"
    )
    assert any(
        r.channel == "telegram" and r.sent_at is None for r in rows
    ), "phải có telegram outbox row pending"
    # in_app coi như delivered ngay
    in_apps = [r for r in rows if r.channel == "in_app"]
    assert len(in_apps) == 1
    assert in_apps[0].sent_at is not None
