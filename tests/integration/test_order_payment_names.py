from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.core.matcher import MatchCandidate, MatchInput, find_order_match
from packages.db.models import Base, Order, allocate_order, normalize_order_code


def test_payment_name_normalization_and_matching() -> None:
    code = "NGO TIEN DAT chuyen tien"
    assert normalize_order_code("  ngo   tien dat CHUYEN TIEN  ") == code
    assert normalize_order_code("dh123456") == "DH123456"
    now = datetime.now(UTC)
    for value, content in [
        (code, "CK NGÔ-TIẾN-ĐẠT CHUYỂN TIỀN trace"),
        ("DH123456", "CK DH-123456"),
    ]:
        order = MatchCandidate("o", value, Decimal(100), "pending", now + timedelta(minutes=1))
        assert (
            find_order_match(MatchInput(Decimal(100), content), [order], now=now).status
            == "matched"
        )
        assert (
            find_order_match(MatchInput(Decimal(101), content), [order], now=now).status
            == "unmatched"
        )
        assert (
            find_order_match(
                MatchInput(Decimal(100), content), [order], now=now + timedelta(minutes=2)
            ).status
            == "unmatched"
        )


async def test_unique_index_and_collision_retry_preserve_existing_orders(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'names.sqlite'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        first = Order.new(amount_vnd=Decimal(100), bank_account_id="b", ttl_seconds=900)
        first.code = "NGO TIEN DAT chuyen tien"
        async with sessions() as session:
            await allocate_order(session, first)
            await session.commit()
        # A separate writer cannot bypass the permanent DB uniqueness rule.
        duplicate = Order.new(amount_vnd=Decimal(200), bank_account_id="other", ttl_seconds=900)
        duplicate.code = first.code
        async with sessions() as session:
            session.add(duplicate)
            with pytest.raises(IntegrityError):
                await session.commit()
        second = Order.new(amount_vnd=Decimal(100), bank_account_id="b", ttl_seconds=900)
        second.transfer_content = first.transfer_content
        monkeypatch.setattr(
            "packages.db.models._generate_order_code", lambda: "LE MINH AN chuyen tien"
        )
        async with sessions() as session:
            await allocate_order(session, second)
            await session.commit()
            assert second.code != first.code
            assert second.transfer_content != first.transfer_content
            assert len((await session.scalars(select(Order))).all()) == 2
    finally:
        await engine.dispose()
