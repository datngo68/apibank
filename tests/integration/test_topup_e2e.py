"""Topup e2e: tạo order kind=topup → giả lập ingest → wallet credit."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from packages.banks.base import BankTransaction
from packages.billing import topup, wallet
from packages.billing.errors import SystemBankNotConfiguredError
from packages.core.ingest import ingest_transaction
from packages.db.models import BankAccount, User
from packages.security.passwords import hash_password


async def _make_user(session: AsyncSession) -> User:
    user = User(email="topup@a.com", password_hash=hash_password("xxxxxxxx"), full_name="T")
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
async def test_create_topup_requires_system_bank(initialized_db: AsyncSession) -> None:
    user = await _make_user(initialized_db)
    with pytest.raises(SystemBankNotConfiguredError):
        await topup.create_topup_order(initialized_db, user=user, amount_vnd=50_000)


@pytest.mark.asyncio
async def test_create_topup_order_attaches_metadata(initialized_db: AsyncSession) -> None:
    user = await _make_user(initialized_db)
    bank = await _make_system_bank(initialized_db)
    order = await topup.create_topup_order(initialized_db, user=user, amount_vnd=50_000)
    await initialized_db.commit()
    assert order.bank_account_id == bank.id
    assert order.metadata_json["kind"] == "topup"
    assert order.metadata_json["user_id"] == user.id
    assert int(order.amount_vnd) == 50_000


@pytest.mark.asyncio
async def test_topup_amount_bounds(initialized_db: AsyncSession) -> None:
    user = await _make_user(initialized_db)
    await _make_system_bank(initialized_db)
    with pytest.raises(ValueError):
        await topup.create_topup_order(initialized_db, user=user, amount_vnd=1_000)
    with pytest.raises(ValueError):
        await topup.create_topup_order(initialized_db, user=user, amount_vnd=100_000_000)


@pytest.mark.asyncio
async def test_ingest_credits_wallet_for_topup(initialized_db: AsyncSession) -> None:
    user = await _make_user(initialized_db)
    bank = await _make_system_bank(initialized_db)
    order = await topup.create_topup_order(initialized_db, user=user, amount_vnd=100_000)
    await initialized_db.commit()

    # Giả lập transaction có nội dung khớp order code
    bank_tx = BankTransaction(
        bank_ref_no="REF-001",
        amount=Decimal(100_000),
        content=f"NAP TIEN {order.code}",
        posted_at=datetime.now(UTC),
        counter_account=None,
        counter_name=None,
        raw={"src": "test"},
    )
    await ingest_transaction(initialized_db, bank_account_id=bank.id, bank_transaction=bank_tx)

    refreshed = await initialized_db.get(User, user.id)
    assert refreshed is not None
    assert Decimal(refreshed.balance_vnd) == Decimal(100_000)


@pytest.mark.asyncio
async def test_topup_credit_idempotent(initialized_db: AsyncSession) -> None:
    user = await _make_user(initialized_db)
    bank = await _make_system_bank(initialized_db)
    order = await topup.create_topup_order(initialized_db, user=user, amount_vnd=80_000)
    await initialized_db.commit()

    # 2 transactions với content khớp → ingest lần 1 match đơn, credit; ingest lần 2
    # không match (đơn đã paid) → balance không tăng thêm.
    tx1 = BankTransaction(
        bank_ref_no="A",
        amount=Decimal(80_000),
        content=order.code,
        posted_at=datetime.now(UTC),
        counter_account=None,
        counter_name=None,
        raw={},
    )
    await ingest_transaction(initialized_db, bank_account_id=bank.id, bank_transaction=tx1)
    refreshed = await initialized_db.get(User, user.id)
    assert refreshed is not None
    assert Decimal(refreshed.balance_vnd) == Decimal(80_000)

    # gọi credit_wallet_for_topup trực tiếp lần nữa với cùng order → không tăng balance
    order_again = await initialized_db.get(type(order), order.id)
    assert order_again is not None
    credited_again = await topup.credit_wallet_for_topup(initialized_db, order_again)
    await initialized_db.commit()
    assert credited_again is False
    refreshed = await initialized_db.get(User, user.id)
    assert refreshed is not None
    assert Decimal(refreshed.balance_vnd) == Decimal(80_000)


@pytest.mark.asyncio
async def test_non_topup_order_not_credited(initialized_db: AsyncSession) -> None:
    """Order thông thường (không có metadata.kind=topup) không trigger credit ví."""
    user = await _make_user(initialized_db)
    bank = await _make_system_bank(initialized_db)
    from packages.db.models import Order

    order = Order.new(
        amount_vnd=Decimal(50_000),
        bank_account_id=bank.id,
        ttl_seconds=900,
        metadata_json={"kind": "shop_order"},
    )
    initialized_db.add(order)
    await initialized_db.commit()

    bank_tx = BankTransaction(
        bank_ref_no="X",
        amount=Decimal(50_000),
        content=order.code,
        posted_at=datetime.now(UTC),
        counter_account=None,
        counter_name=None,
        raw={},
    )
    await ingest_transaction(initialized_db, bank_account_id=bank.id, bank_transaction=bank_tx)
    refreshed = await initialized_db.get(User, user.id)
    assert refreshed is not None
    assert Decimal(refreshed.balance_vnd) == Decimal(0)


@pytest.mark.asyncio
async def test_get_system_bank_when_set(initialized_db: AsyncSession) -> None:
    bank = await _make_system_bank(initialized_db)
    await initialized_db.commit()
    found = await topup.get_system_bank(initialized_db)
    assert found.id == bank.id


@pytest.mark.asyncio
async def test_wallet_consistency_after_multiple_topups(initialized_db: AsyncSession) -> None:
    user = await _make_user(initialized_db)
    bank = await _make_system_bank(initialized_db)
    total = Decimal(0)
    for i in range(3):
        order = await topup.create_topup_order(
            initialized_db, user=user, amount_vnd=10_000 * (i + 1)
        )
        await initialized_db.commit()
        bank_tx = BankTransaction(
            bank_ref_no=f"R{i}",
            amount=Decimal(order.amount_vnd),
            content=order.code,
            posted_at=datetime.now(UTC),
            counter_account=None,
            counter_name=None,
            raw={},
        )
        await ingest_transaction(
            initialized_db, bank_account_id=bank.id, bank_transaction=bank_tx
        )
        total += Decimal(order.amount_vnd)
    refreshed = await initialized_db.get(User, user.id)
    assert refreshed is not None
    assert Decimal(refreshed.balance_vnd) == total
    txs = await wallet.list_transactions(initialized_db, user_id=user.id)
    assert len(txs) == 3
