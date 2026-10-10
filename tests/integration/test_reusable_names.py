from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.core.ingest import _try_match_transaction
from packages.db.models import (
    Base,
    Order,
    PaymentNamePoolFull,
    PaymentNameReservation,
    Transaction,
    allocate_order,
)


async def test_reuse_and_conservative_matching(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'pool.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    name = "NGO TIEN DAT chuyen tien"
    now = datetime.now(UTC)
    monkeypatch.setattr("packages.db.models._payment_names", lambda: [name])
    monkeypatch.setattr("packages.db.models.utcnow", lambda: now)
    async with sessions() as session:
        first = Order.new(amount_vnd=Decimal(100), bank_account_id="b", ttl_seconds=900)
        await allocate_order(session, first)
        await session.commit()
        assert first.code != first.transfer_content == name
        with pytest.raises(PaymentNamePoolFull):
            await allocate_order(
                session, Order.new(amount_vnd=Decimal(100), bank_account_id="b", ttl_seconds=900)
            )
        other = Order.new(amount_vnd=Decimal(100), bank_account_id="other", ttl_seconds=900)
        await allocate_order(session, other)
        assert other.transfer_content == name
        await session.commit()
        reservation = await session.get(PaymentNameReservation, ("b", name))
        assert reservation.reserved_until.replace(tzinfo=UTC) == first.expired_at + timedelta(
            days=7
        )
        first.status = "expired"
        now = first.expired_at + timedelta(days=7) - timedelta(microseconds=1)
        with pytest.raises(PaymentNamePoolFull):
            await allocate_order(
                session, Order.new(amount_vnd=Decimal(100), bank_account_id="b", ttl_seconds=900)
            )
        now += timedelta(microseconds=1)
        second = Order.new(amount_vnd=Decimal(100), bank_account_id="b", ttl_seconds=900)
        second.created_at = now
        await allocate_order(session, second)
        await session.commit()
        assert second.code != first.code and second.transfer_content == first.transfer_content
        tx = Transaction(
            bank_account_id="b",
            bank_ref_no="late",
            amount_vnd=100,
            content=name,
            posted_at=first.expired_at,
            timestamp_reliable=True,
        )
        session.add(tx)
        await session.flush()
        event, _ = await _try_match_transaction(session, tx)
        assert event is None and second.status == "pending"
        tx.posted_at = now
        event, _ = await _try_match_transaction(session, tx)
        assert event is not None and tx.state == "matched" and second.status == "paid"
        assert tx.matched_order_id == second.id
        assert reservation.reserved_until.replace(tzinfo=UTC) == second.paid_at + timedelta(days=7)
    async with sessions() as session:
        session.add(PaymentNameReservation(bank_account_id="b", content=name, reserved_until=now))
        with pytest.raises(IntegrityError):
            await session.commit()
    await engine.dispose()


async def test_more_than_18000_historical_orders(tmp_path):
    from sqlalchemy import insert

    from packages.db.models import _payment_names

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'history.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        names = _payment_names()
        old = datetime.now(UTC) - timedelta(days=30)
        await conn.execute(
            insert(Order),
            [
                dict(
                    id=f"old{i}",
                    code=f"HIST{i}",
                    transfer_content=names[i % len(names)],
                    amount_vnd=100,
                    bank_account_id="b",
                    status="expired",
                    expired_at=old,
                    created_at=old,
                    updated_at=old,
                )
                for i in range(18001)
            ],
        )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        order = Order.new(amount_vnd=Decimal(100), bank_account_id="b", ttl_seconds=900)
        await allocate_order(session, order)
        await session.commit()
        assert order.transfer_content in names and order.code.startswith("PAY")
    await engine.dispose()
