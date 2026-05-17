"""Phase 5: webhook dispatcher atomic claim — chống double-deliver.

Chạy 2 task ``dispatch_due_attempts`` đồng thời với cùng pool attempts,
mỗi task có session riêng (mô phỏng 2 worker độc lập). Tổng số delivered
phải = N (số attempt unique), không có double-deliver.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.db.models import (
    BankAccount,
    Base,
    Order,
    Transaction,
    Webhook,
    WebhookAttempt,
)
from packages.webhook.dispatcher import (
    dispatch_due_attempts,
    reset_stuck_dispatching,
)


async def _make_shared_engine(tmp_path: Path):  # type: ignore[no-untyped-def]
    """File-based SQLite (tmp) — 2 session thấy cùng DB.

    `:memory:` + `cache=shared` không reliable với aiosqlite trên Windows;
    file-based đảm bảo cùng schema giữa các connections trong test.
    """
    db_path = tmp_path / "atomic_claim.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path.as_posix()}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


async def _seed_attempts(session, n: int) -> list[str]:  # type: ignore[no-untyped-def]
    bank = BankAccount(
        id="ba_atomic",
        bank_code="MB",
        account_no="000",
        account_holder="X",
        credentials_enc="x",
        status="active",
        polling_enabled=True,
        created_at=datetime.now(UTC),
    )
    webhook = Webhook(
        id="wh_atomic",
        owner_id="default",
        url="https://example.test/hook",
        secret_enc="topsecret",
        active=True,
        headers_json={},
        created_at=datetime.now(UTC),
    )
    session.add_all([bank, webhook])
    ids: list[str] = []
    for i in range(n):
        order = Order.new(
            amount_vnd=Decimal("10000"), bank_account_id=bank.id, ttl_seconds=900
        )
        tx = Transaction(
            bank_account_id=bank.id,
            bank_ref_no=f"REF{i}",
            amount_vnd=Decimal("10000"),
            content="ANY",
            posted_at=datetime.now(UTC),
            raw_json={},
            state="matched",
        )
        session.add_all([order, tx])
        await session.flush()
        attempt = WebhookAttempt.new(
            webhook_id=webhook.id,
            order_id=order.id,
            transaction_id=tx.id,
            payload={"i": i},
        )
        session.add(attempt)
        await session.flush()
        ids.append(attempt.id)
    await session.commit()
    return ids


@pytest.mark.asyncio
async def test_concurrent_dispatchers_do_not_double_deliver(tmp_path: Path) -> None:
    engine = await _make_shared_engine(tmp_path)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as seed_session:
            ids = await _seed_attempts(seed_session, n=10)

        call_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            # Tạo delay nhỏ để 2 dispatcher chạy chồng pha HTTP, làm
            # sharper test concurrency.
            await asyncio.sleep(0.01)
            return httpx.Response(200, text="ok")

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:

            async def run_dispatcher() -> int:
                async with sessionmaker() as session:
                    return await dispatch_due_attempts(
                        session, client=client, batch_size=20
                    )

            r1, r2 = await asyncio.gather(
                run_dispatcher(), run_dispatcher(), return_exceptions=True
            )

        delivered_total = (r1 if isinstance(r1, int) else 0) + (
            r2 if isinstance(r2, int) else 0
        )
        assert delivered_total == len(ids), (
            f"delivered={delivered_total} expected={len(ids)} r1={r1} r2={r2}"
        )
        assert call_count == len(ids), (
            f"HTTP call count = {call_count}, expected {len(ids)} (no double-deliver)"
        )

        async with sessionmaker() as verify:
            for aid in ids:
                a = await verify.get(WebhookAttempt, aid)
                assert a is not None
                assert a.status == "delivered"
                assert a.attempt == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reset_stuck_dispatching_recovers_crashed_attempts(
    tmp_path: Path,
) -> None:
    """Attempt ở 'dispatching' lâu hơn ngưỡng → reset về 'pending'."""
    engine = await _make_shared_engine(tmp_path)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            ids = await _seed_attempts(session, n=2)
            stuck = await session.get(WebhookAttempt, ids[0])
            assert stuck is not None
            stuck.status = "dispatching"
            stuck.claimed_at = datetime.now(UTC) - timedelta(minutes=10)
            await session.commit()

            reset = await reset_stuck_dispatching(session)
            assert reset == 1

            await session.refresh(stuck)
            assert stuck.status == "pending"
            assert stuck.claimed_at is None
    finally:
        await engine.dispose()
