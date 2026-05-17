from datetime import UTC, datetime, timedelta
from decimal import Decimal

from packages.core.reconcile_runner import expire_overdue_orders, reconcile
from packages.db.models import BankAccount, Order
from tests.helpers.in_memory_db import build_session


async def _seed_account(session) -> None:  # type: ignore[no-untyped-def]
    session.add(
        BankAccount(
            id="ba_1",
            bank_code="MB",
            account_no="123",
            account_holder="x",
            credentials_enc="enc",
            status="active",
            polling_enabled=True,
            created_at=datetime.now(UTC),
        )
    )


async def test_expire_overdue_orders_marks_pending_expired() -> None:
    async for session in build_session():
        await _seed_account(session)
        order = Order.new(amount_vnd=Decimal("100"), bank_account_id="ba_1", ttl_seconds=1)
        order.expired_at = datetime.now(UTC) - timedelta(seconds=10)
        session.add(order)
        await session.flush()

        count = await expire_overdue_orders(session)
        await session.refresh(order)

        assert count == 1
        assert order.status == "expired"


async def test_reconcile_returns_report() -> None:
    async for session in build_session():
        await _seed_account(session)
        await session.flush()

        report = await reconcile(session)

        assert report.imported_transactions == 0
        assert report.matched_orders == 0
        assert report.unmatched_transactions == 0


async def test_reconcile_counts_by_state_via_group_by() -> None:
    """GROUP BY thay vì select toàn bộ row — verify count đúng theo state."""
    from packages.db.models import Transaction

    async for session in build_session():
        await _seed_account(session)
        # Seed 3 matched, 2 unmatched, 1 review.
        for i in range(3):
            session.add(
                Transaction(
                    bank_account_id="ba_1",
                    bank_ref_no=f"M{i}",
                    amount_vnd=Decimal("100"),
                    content=f"M{i}",
                    posted_at=datetime.now(UTC),
                    raw_json={},
                    state="matched",
                )
            )
        for i in range(2):
            session.add(
                Transaction(
                    bank_account_id="ba_1",
                    bank_ref_no=f"U{i}",
                    amount_vnd=Decimal("100"),
                    content=f"U{i}",
                    posted_at=datetime.now(UTC),
                    raw_json={},
                    state="unmatched",
                )
            )
        session.add(
            Transaction(
                bank_account_id="ba_1",
                bank_ref_no="R0",
                amount_vnd=Decimal("100"),
                content="R0",
                posted_at=datetime.now(UTC),
                raw_json={},
                state="review",
            )
        )
        await session.flush()

        report = await reconcile(session)

        assert report.imported_transactions == 6
        assert report.matched_orders == 3
        assert report.unmatched_transactions == 2
        assert report.review_transactions == 1
