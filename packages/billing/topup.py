"""Topup flow: tạo Order kind=topup gắn system bank account, hook ingest.

Khi `Order.metadata_json["kind"] == "topup"` được match (paid), wallet được credit.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.billing import wallet
from packages.billing.errors import SystemBankNotConfiguredError
from packages.db.models import BankAccount, Order, User, utcnow

TOPUP_KIND: Final = "topup"
TOPUP_TTL_SECONDS: Final = 24 * 60 * 60  # 24h
MIN_TOPUP_VND: Final = Decimal(2_000)
MAX_TOPUP_VND: Final = Decimal(50_000_000)


async def get_system_bank(session: AsyncSession) -> BankAccount:
    bank = (
        await session.scalars(
            select(BankAccount)
            .where(BankAccount.is_system_account.is_(True))
            .where(BankAccount.status == "active")
        )
    ).first()
    if bank is None:
        raise SystemBankNotConfiguredError(
            "no system bank account configured; run `apimb system-bank set --account-id ...`"
        )
    return bank


async def create_topup_order(
    session: AsyncSession,
    *,
    user: User,
    amount_vnd: Decimal | int,
    ttl_seconds: int = TOPUP_TTL_SECONDS,
) -> Order:
    """Tạo Order với metadata kind=topup. Caller commit."""
    amt = Decimal(amount_vnd)
    if amt < MIN_TOPUP_VND or amt > MAX_TOPUP_VND:
        raise ValueError(
            f"topup amount must be in [{int(MIN_TOPUP_VND):,}, {int(MAX_TOPUP_VND):,}]"
        )
    bank = await get_system_bank(session)
    order = Order.new(
        amount_vnd=amt,
        bank_account_id=bank.id,
        ttl_seconds=ttl_seconds,
        description=f"Nạp ví {int(amt):,} VND",
        customer_ref=user.email,
        metadata_json={"kind": TOPUP_KIND, "user_id": user.id},
        user_id=user.id,
    )
    session.add(order)
    await session.flush()
    return order


def is_topup_order(order: Order) -> bool:
    return bool(order.metadata_json or {}).__bool__() and (
        (order.metadata_json or {}).get("kind") == TOPUP_KIND
    )


async def credit_wallet_for_topup(session: AsyncSession, order: Order) -> bool:
    """Credit ví user khi topup order trở thành paid.

    Idempotency_key dùng `topup:{order.id}` để re-call an toàn.
    Trả True nếu thực sự credit (lần đầu), False nếu đã credit trước đó.
    """
    if not is_topup_order(order):
        return False
    user_id = (order.metadata_json or {}).get("user_id")
    if not user_id:
        return False
    user = await session.get(User, user_id)
    if user is None:
        return False
    before = Decimal(user.balance_vnd)
    tx = await wallet.credit(
        session,
        user_id=user_id,
        amount_vnd=Decimal(order.amount_vnd),
        idempotency_key=f"topup:{order.id}",
        ref_kind="order",
        ref_id=order.id,
        note=f"Topup từ đơn {order.code}",
        created_by="system:ingest",
    )
    return Decimal(tx.balance_after) > before


def is_expired(order: Order) -> bool:
    expires = order.expired_at
    if expires is None:
        return False
    if expires.tzinfo is None:
        from datetime import UTC

        expires = expires.replace(tzinfo=UTC)
    return expires < utcnow()


def time_remaining(order: Order) -> timedelta:
    expires = order.expired_at
    now: datetime = utcnow()
    if expires is None:
        return timedelta(0)
    if expires.tzinfo is None:
        from datetime import UTC

        expires = expires.replace(tzinfo=UTC)
    diff = expires - now
    return diff if diff > timedelta(0) else timedelta(0)
