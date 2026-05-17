from datetime import UTC, datetime
from decimal import Decimal

import httpx

from packages.db.models import Order, Transaction, Webhook, WebhookAttempt
from packages.webhook.dispatcher import dispatch_due_attempts, schedule_next
from tests.helpers.in_memory_db import build_session


def test_schedule_next_uses_exponential_table() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    assert (schedule_next(0, now=base) - base).total_seconds() == 0
    assert (schedule_next(1, now=base) - base).total_seconds() == 30
    assert (schedule_next(6, now=base) - base).total_seconds() == 86400
    assert (schedule_next(99, now=base) - base).total_seconds() == 86400


async def _seed_attempt(session) -> WebhookAttempt:  # type: ignore[no-untyped-def]
    webhook = Webhook(
        id="wh_1",
        owner_id="default",
        url="https://example.test/hook",
        secret_enc="topsecret",
        active=True,
        headers_json={},
        created_at=datetime.now(UTC),
    )
    order = Order.new(amount_vnd=Decimal("10000"), bank_account_id="ba_1", ttl_seconds=900)
    transaction = Transaction(
        bank_account_id="ba_1",
        bank_ref_no="FT_X",
        amount_vnd=Decimal("10000"),
        content="ANY",
        posted_at=datetime.now(UTC),
        raw_json={},
        state="matched",
    )
    session.add_all([webhook, order, transaction])
    await session.flush()
    attempt = WebhookAttempt.new(
        webhook_id=webhook.id,
        order_id=order.id,
        transaction_id=transaction.id,
        payload={"hello": "world"},
    )
    session.add(attempt)
    await session.flush()
    return attempt


async def test_dispatch_marks_attempt_delivered_on_2xx() -> None:
    async for session in build_session():
        attempt = await _seed_attempt(session)
        transport = httpx.MockTransport(lambda request: httpx.Response(200, text="ok"))
        async with httpx.AsyncClient(transport=transport) as client:
            delivered = await dispatch_due_attempts(session, client=client)
        await session.refresh(attempt)
        assert delivered == 1
        assert attempt.status == "delivered"
        assert attempt.last_status_code == 200


async def test_dispatch_reschedules_on_5xx_until_dead() -> None:
    async for session in build_session():
        attempt = await _seed_attempt(session)
        attempt.max_attempts = 2
        await session.flush()
        transport = httpx.MockTransport(lambda request: httpx.Response(500, text="boom"))
        async with httpx.AsyncClient(transport=transport) as client:
            await dispatch_due_attempts(session, client=client)
            await session.refresh(attempt)
            assert attempt.status == "pending"
            assert attempt.attempt == 1

            attempt.next_run_at = datetime.now(UTC)
            await session.commit()

            await dispatch_due_attempts(session, client=client)
            await session.refresh(attempt)
            assert attempt.status == "dead"
            assert attempt.attempt == 2
