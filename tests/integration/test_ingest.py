from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from packages.banks.base import BankTransaction
from packages.core.ingest import ingest_transaction
from packages.db.models import BankAccount, Order, Webhook
from tests.helpers.in_memory_db import build_session


async def _seed_account(session) -> BankAccount:  # type: ignore[no-untyped-def]
    account = BankAccount(
        id="ba_1",
        bank_code="MB",
        account_no="1234567890",
        account_holder="Tester",
        credentials_enc="enc",
        status="active",
        polling_enabled=True,
        created_at=datetime.now(UTC),
    )
    session.add(account)
    return account


async def test_ingest_unmatched_transaction_persists_state_unmatched() -> None:
    async for session in build_session():
        await _seed_account(session)
        await session.flush()

        bank_tx = BankTransaction(
            bank_ref_no="FT001",
            posted_at=datetime.now(UTC),
            amount=Decimal("100000"),
            content="GIAO DICH KHONG MA",
            counter_account=None,
            counter_name=None,
            raw={},
        )

        result = await ingest_transaction(session, bank_account_id="ba_1", bank_transaction=bank_tx)

        assert result.state == "unmatched"
        assert result.matched_order_id is None


async def test_ingest_matching_order_marks_paid_and_enqueues_webhook() -> None:
    async for session in build_session():
        await _seed_account(session)
        order = Order.new(
            amount_vnd=Decimal("150000"), bank_account_id="ba_1", ttl_seconds=900
        )
        session.add(order)
        webhook = Webhook(
            id="wh_1",
            owner_id="default",
            url="https://example.com/hook",
            secret_enc="topsecret",
            active=True,
            headers_json={},
            created_at=datetime.now(UTC),
        )
        session.add(webhook)
        await session.flush()

        bank_tx = BankTransaction(
            bank_ref_no="FT002",
            posted_at=datetime.now(UTC),
            amount=Decimal("150000"),
            content=f"NAP TIEN {order.code}",
            counter_account=None,
            counter_name=None,
            raw={},
        )

        result = await ingest_transaction(session, bank_account_id="ba_1", bank_transaction=bank_tx)
        await session.refresh(order)

        assert result.state == "matched"
        assert result.matched_order_id == order.id
        assert order.status == "paid"
        assert order.paid_tx_id == result.id
