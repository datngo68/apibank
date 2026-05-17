"""Tests cho subscription/invoice/plans_seed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from packages.billing import subscription, wallet
from packages.billing.errors import InsufficientFundsError, PlanNotFoundError
from packages.billing.plans_seed import seed_plans
from packages.db.models import Invoice, Subscription, User
from packages.security.passwords import hash_password


async def _user_with_balance(session: AsyncSession, balance: int = 100_000) -> User:
    user = User(email="s@a.com", password_hash=hash_password("xxxxxxxx"), full_name="S")
    session.add(user)
    await session.flush()
    if balance:
        await wallet.credit(
            session,
            user_id=user.id,
            amount_vnd=balance,
            idempotency_key=f"seed:{user.id}",
        )
    return user


@pytest.fixture
async def seeded(initialized_db: AsyncSession) -> AsyncSession:
    await seed_plans(initialized_db)
    await initialized_db.commit()
    return initialized_db


@pytest.mark.asyncio
async def test_seed_idempotent(initialized_db: AsyncSession) -> None:
    a = await seed_plans(initialized_db)
    await initialized_db.commit()
    b = await seed_plans(initialized_db)
    await initialized_db.commit()
    assert a == 3
    assert b == 0


@pytest.mark.asyncio
async def test_get_plan_unknown(seeded: AsyncSession) -> None:
    with pytest.raises(PlanNotFoundError):
        await subscription.get_plan(seeded, "nope")


@pytest.mark.asyncio
async def test_purchase_creates_subscription_and_invoice(seeded: AsyncSession) -> None:
    user = await _user_with_balance(seeded, 50_000)
    sub, invoice = await subscription.purchase(
        seeded, user=user, plan_code="monthly", idempotency_key="p1"
    )
    await seeded.commit()
    assert sub.status == "active"
    assert invoice.status == "paid"
    assert invoice.plan_code == "monthly"
    refreshed = await seeded.get(User, user.id)
    assert refreshed is not None
    assert Decimal(refreshed.balance_vnd) == Decimal(35_000)  # 50k - 15k


@pytest.mark.asyncio
async def test_insufficient_balance_blocks_purchase(seeded: AsyncSession) -> None:
    user = await _user_with_balance(seeded, 0)
    with pytest.raises(InsufficientFundsError):
        await subscription.purchase(seeded, user=user, plan_code="monthly")


@pytest.mark.asyncio
async def test_renew_extends_expires_at(seeded: AsyncSession) -> None:
    user = await _user_with_balance(seeded, 200_000)
    sub1, _ = await subscription.purchase(
        seeded, user=user, plan_code="monthly", idempotency_key="r1"
    )
    await seeded.commit()
    first_exp = sub1.expires_at
    sub2, _ = await subscription.purchase(
        seeded, user=user, plan_code="monthly", idempotency_key="r2"
    )
    await seeded.commit()
    assert sub2.id == sub1.id
    # SQLite có thể trả naive datetime; chuẩn hoá về cùng tz để so sánh
    a = sub2.expires_at.replace(tzinfo=None) if sub2.expires_at.tzinfo else sub2.expires_at
    b = first_exp.replace(tzinfo=None) if first_exp.tzinfo else first_exp
    delta = a - b
    # +30 ngày
    assert timedelta(days=29) <= delta <= timedelta(days=31)


@pytest.mark.asyncio
async def test_purchase_idempotent(seeded: AsyncSession) -> None:
    user = await _user_with_balance(seeded, 50_000)
    a, _ = await subscription.purchase(
        seeded, user=user, plan_code="trial-day", idempotency_key="dup"
    )
    await seeded.commit()
    b, _ = await subscription.purchase(
        seeded, user=user, plan_code="trial-day", idempotency_key="dup"
    )
    await seeded.commit()
    assert a.id == b.id  # cùng sub
    refreshed = await seeded.get(User, user.id)
    assert refreshed is not None
    assert Decimal(refreshed.balance_vnd) == Decimal(49_000)  # chỉ trừ 1k 1 lần


@pytest.mark.asyncio
async def test_get_active_subscription_none_when_no_sub(seeded: AsyncSession) -> None:
    user = await _user_with_balance(seeded, 100)
    assert await subscription.get_active_subscription(seeded, user.id) is None


@pytest.mark.asyncio
async def test_expire_due_subscriptions(seeded: AsyncSession) -> None:
    user = await _user_with_balance(seeded, 200_000)
    sub, _ = await subscription.purchase(
        seeded, user=user, plan_code="monthly", idempotency_key="e1"
    )
    sub.expires_at = datetime.now(UTC) - timedelta(days=1)
    await seeded.commit()
    n = await subscription.expire_due_subscriptions(seeded)
    await seeded.commit()
    assert n == 1
    refreshed = await seeded.get(Subscription, sub.id)
    assert refreshed is not None and refreshed.status == "expired"


@pytest.mark.asyncio
async def test_change_plan_with_prorate_refund(seeded: AsyncSession) -> None:
    user = await _user_with_balance(seeded, 200_000)
    sub, _ = await subscription.purchase(
        seeded, user=user, plan_code="monthly", idempotency_key="cp1"
    )
    await seeded.commit()
    # Sau 0 ngày → refund ~15k, mua mới plan trial 1k
    new_sub, new_invoice = await subscription.change_plan(
        seeded, user=user, new_plan_code="trial-day", idempotency_key="cp2"
    )
    await seeded.commit()
    assert new_invoice.plan_code == "trial-day"
    assert new_sub.id != sub.id
    refreshed = await seeded.get(User, user.id)
    assert refreshed is not None
    # 200k - 15k (mua monthly) + ~15k refund - 1k (trial) ≈ 199k
    assert Decimal(refreshed.balance_vnd) >= Decimal(195_000)


@pytest.mark.asyncio
async def test_list_invoices_returns_recent_first(seeded: AsyncSession) -> None:
    user = await _user_with_balance(seeded, 200_000)
    await subscription.purchase(seeded, user=user, plan_code="trial-day", idempotency_key="i1")
    await seeded.commit()
    await subscription.purchase(seeded, user=user, plan_code="trial-day", idempotency_key="i2")
    await seeded.commit()
    invoices = await subscription.list_invoices(seeded, user.id)
    assert len(invoices) == 2
    assert invoices[0].issued_at >= invoices[1].issued_at


@pytest.mark.asyncio
async def test_has_active_subscription_flag(seeded: AsyncSession) -> None:
    user = await _user_with_balance(seeded, 100_000)
    assert await subscription.has_active_subscription(seeded, user.id) is False
    await subscription.purchase(seeded, user=user, plan_code="trial-day", idempotency_key="hf")
    await seeded.commit()
    assert await subscription.has_active_subscription(seeded, user.id) is True


@pytest.mark.asyncio
async def test_invoice_links_to_wallet_tx(seeded: AsyncSession) -> None:
    user = await _user_with_balance(seeded, 100_000)
    _, invoice = await subscription.purchase(
        seeded, user=user, plan_code="trial-day", idempotency_key="lw"
    )
    await seeded.commit()
    fresh = await seeded.get(Invoice, invoice.id)
    assert fresh is not None and fresh.wallet_tx_id


@pytest.mark.asyncio
async def test_change_plan_when_no_existing(seeded: AsyncSession) -> None:
    user = await _user_with_balance(seeded, 100_000)
    sub, invoice = await subscription.change_plan(
        seeded, user=user, new_plan_code="monthly", idempotency_key="cp-new"
    )
    await seeded.commit()
    assert sub.status == "active"
    assert invoice.plan_code == "monthly"
