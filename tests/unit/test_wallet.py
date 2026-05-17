"""Unit tests cho wallet ledger."""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.billing import wallet
from packages.billing.errors import IdempotencyConflictError, InsufficientFundsError
from packages.db.models import User, WalletTransaction
from packages.security.passwords import hash_password


async def _make_user(session: AsyncSession, *, email: str = "u@a.com") -> User:
    user = User(email=email, password_hash=hash_password("xxxxxxxx"), full_name="U")
    session.add(user)
    await session.flush()
    return user


async def _balance(session: AsyncSession, user: User) -> Decimal:
    refreshed = await session.get(User, user.id)
    assert refreshed is not None
    return Decimal(refreshed.balance_vnd)


async def _ledger_sum(session: AsyncSession, user_id: str) -> Decimal:
    res = await session.execute(
        select(func.coalesce(func.sum(WalletTransaction.amount_vnd), 0)).where(
            WalletTransaction.user_id == user_id
        )
    )
    return Decimal(res.scalar_one() or 0)


@pytest.mark.asyncio
async def test_credit_increases_balance(initialized_db: AsyncSession) -> None:
    user = await _make_user(initialized_db)
    await wallet.credit(initialized_db, user_id=user.id, amount_vnd=50_000, idempotency_key="k1")
    await initialized_db.commit()
    assert await _balance(initialized_db, user) == Decimal(50_000)


@pytest.mark.asyncio
async def test_debit_requires_sufficient_balance(initialized_db: AsyncSession) -> None:
    user = await _make_user(initialized_db)
    with pytest.raises(InsufficientFundsError):
        await wallet.debit(initialized_db, user_id=user.id, amount_vnd=1, idempotency_key="d1")


@pytest.mark.asyncio
async def test_debit_decreases_balance(initialized_db: AsyncSession) -> None:
    user = await _make_user(initialized_db)
    await wallet.credit(initialized_db, user_id=user.id, amount_vnd=100, idempotency_key="c1")
    await initialized_db.commit()
    await wallet.debit(initialized_db, user_id=user.id, amount_vnd=40, idempotency_key="d1")
    await initialized_db.commit()
    assert await _balance(initialized_db, user) == Decimal(60)


@pytest.mark.asyncio
async def test_idempotent_credit(initialized_db: AsyncSession) -> None:
    user = await _make_user(initialized_db)
    a = await wallet.credit(initialized_db, user_id=user.id, amount_vnd=1000, idempotency_key="x")
    await initialized_db.commit()
    b = await wallet.credit(initialized_db, user_id=user.id, amount_vnd=1000, idempotency_key="x")
    await initialized_db.commit()
    assert a.id == b.id
    assert await _balance(initialized_db, user) == Decimal(1000)


@pytest.mark.asyncio
async def test_idempotency_conflict_on_different_amount(initialized_db: AsyncSession) -> None:
    user = await _make_user(initialized_db)
    await wallet.credit(initialized_db, user_id=user.id, amount_vnd=500, idempotency_key="dup")
    await initialized_db.commit()
    with pytest.raises(IdempotencyConflictError):
        await wallet.credit(
            initialized_db, user_id=user.id, amount_vnd=600, idempotency_key="dup"
        )


@pytest.mark.asyncio
async def test_idempotency_conflict_on_different_user(initialized_db: AsyncSession) -> None:
    u1 = await _make_user(initialized_db, email="a@a.com")
    u2 = await _make_user(initialized_db, email="b@b.com")
    await wallet.credit(initialized_db, user_id=u1.id, amount_vnd=100, idempotency_key="conflict")
    await initialized_db.commit()
    with pytest.raises(IdempotencyConflictError):
        await wallet.credit(
            initialized_db, user_id=u2.id, amount_vnd=100, idempotency_key="conflict"
        )


@pytest.mark.asyncio
async def test_refund_increases_balance(initialized_db: AsyncSession) -> None:
    user = await _make_user(initialized_db)
    await wallet.refund(
        initialized_db,
        user_id=user.id,
        amount_vnd=Decimal(250),
        idempotency_key="rf1",
        ref_kind="invoice",
        ref_id="inv_x",
    )
    await initialized_db.commit()
    assert await _balance(initialized_db, user) == Decimal(250)


@pytest.mark.asyncio
async def test_zero_amount_rejected(initialized_db: AsyncSession) -> None:
    user = await _make_user(initialized_db)
    with pytest.raises(ValueError):
        await wallet.credit(
            initialized_db, user_id=user.id, amount_vnd=0, idempotency_key="z"
        )


@pytest.mark.asyncio
async def test_negative_amount_rejected(initialized_db: AsyncSession) -> None:
    user = await _make_user(initialized_db)
    with pytest.raises(ValueError):
        await wallet.credit(
            initialized_db, user_id=user.id, amount_vnd=-100, idempotency_key="n"
        )
    with pytest.raises(ValueError):
        await wallet.debit(
            initialized_db, user_id=user.id, amount_vnd=-100, idempotency_key="n2"
        )


@pytest.mark.asyncio
async def test_unknown_user_rejected(initialized_db: AsyncSession) -> None:
    with pytest.raises(ValueError):
        await wallet.credit(
            initialized_db, user_id="usr_nope", amount_vnd=10, idempotency_key="zz"
        )


@pytest.mark.asyncio
async def test_invariant_balance_equals_ledger_sum(initialized_db: AsyncSession) -> None:
    user = await _make_user(initialized_db)
    await wallet.credit(initialized_db, user_id=user.id, amount_vnd=100, idempotency_key="i1")
    await wallet.credit(initialized_db, user_id=user.id, amount_vnd=200, idempotency_key="i2")
    await wallet.debit(initialized_db, user_id=user.id, amount_vnd=50, idempotency_key="i3")
    await wallet.refund(initialized_db, user_id=user.id, amount_vnd=10, idempotency_key="i4")
    await initialized_db.commit()
    assert await _balance(initialized_db, user) == await _ledger_sum(initialized_db, user.id)
    assert await _balance(initialized_db, user) == Decimal(260)


@pytest.mark.asyncio
async def test_balance_after_recorded(initialized_db: AsyncSession) -> None:
    user = await _make_user(initialized_db)
    await wallet.credit(initialized_db, user_id=user.id, amount_vnd=100, idempotency_key="b1")
    tx = await wallet.credit(
        initialized_db, user_id=user.id, amount_vnd=50, idempotency_key="b2"
    )
    await initialized_db.commit()
    assert Decimal(tx.balance_after) == Decimal(150)


@pytest.mark.asyncio
async def test_list_transactions_returns_recent_first(initialized_db: AsyncSession) -> None:
    user = await _make_user(initialized_db)
    for i in range(3):
        await wallet.credit(
            initialized_db, user_id=user.id, amount_vnd=10 * (i + 1), idempotency_key=f"l{i}"
        )
        await initialized_db.commit()
    rows = await wallet.list_transactions(initialized_db, user_id=user.id)
    assert len(rows) == 3
    # Newest first → first row có balance_after lớn nhất
    assert rows[0].balance_after >= rows[-1].balance_after


@pytest.mark.asyncio
async def test_adjust_can_be_negative(initialized_db: AsyncSession) -> None:
    user = await _make_user(initialized_db)
    await wallet.credit(initialized_db, user_id=user.id, amount_vnd=100, idempotency_key="a1")
    await initialized_db.commit()
    await wallet.adjust(
        initialized_db,
        user_id=user.id,
        amount_vnd=-30,
        idempotency_key="a2",
        note="manual",
        created_by="admin",
    )
    await initialized_db.commit()
    assert await _balance(initialized_db, user) == Decimal(70)


@pytest.mark.asyncio
async def test_isolation_between_users(initialized_db: AsyncSession) -> None:
    u1 = await _make_user(initialized_db, email="x@x.com")
    u2 = await _make_user(initialized_db, email="y@y.com")
    await wallet.credit(initialized_db, user_id=u1.id, amount_vnd=100, idempotency_key="iso1")
    await wallet.credit(initialized_db, user_id=u2.id, amount_vnd=200, idempotency_key="iso2")
    await initialized_db.commit()
    assert await _balance(initialized_db, u1) == Decimal(100)
    assert await _balance(initialized_db, u2) == Decimal(200)


_ = asyncio
