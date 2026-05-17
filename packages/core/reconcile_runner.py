from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.core.reconcile import ReconcileReport
from packages.db.models import Order, Transaction, utcnow


async def expire_overdue_orders(session: AsyncSession, *, now: datetime | None = None) -> int:
    current = now or datetime.now(UTC)
    overdue = (
        await session.scalars(
            select(Order)
            .where(Order.status == "pending")
            .where(Order.expired_at <= current)
        )
    ).all()
    for order in overdue:
        order.status = "expired"
        order.updated_at = current
    await session.commit()
    return len(overdue)


async def detect_silent_payments(
    session: AsyncSession, *, now: datetime | None = None
) -> list[tuple[str, str]]:
    """Find expired orders that have a same-amount unmatched transaction."""

    current = now or datetime.now(UTC)
    suspects: list[tuple[str, str]] = []
    expired_orders = (
        await session.scalars(
            select(Order)
            .where(Order.status == "expired")
            .where(Order.expired_at >= current.replace(hour=0, minute=0, second=0, microsecond=0))
        )
    ).all()
    for order in expired_orders:
        candidates = (
            await session.scalars(
                select(Transaction)
                .where(Transaction.bank_account_id == order.bank_account_id)
                .where(Transaction.amount_vnd == Decimal(order.amount_vnd))
                .where(Transaction.matched_order_id.is_(None))
            )
        ).all()
        for tx in candidates:
            suspects.append((order.id, tx.id))
    return suspects


async def reconcile(session: AsyncSession, *, now: datetime | None = None) -> ReconcileReport:
    await expire_overdue_orders(session, now=now)
    suspects = await detect_silent_payments(session, now=now)

    # GROUP BY thay vì select toàn bộ Transaction. Khi DB có triệu row,
    # query cũ load hết vào RAM mỗi 5 phút — không cần thiết khi chỉ
    # cần count theo state.
    rows = list(
        (
            await session.execute(
                select(Transaction.state, func.count(Transaction.id)).group_by(
                    Transaction.state
                )
            )
        ).all()
    )
    counts: dict[str, int] = {state or "": int(count) for state, count in rows}
    total = sum(counts.values())
    matched = counts.get("matched", 0)
    unmatched = counts.get("unmatched", 0)
    review = counts.get("review", 0) + len(suspects)
    return ReconcileReport(
        imported_transactions=total,
        matched_orders=matched,
        unmatched_transactions=unmatched,
        review_transactions=review,
    )


_ = utcnow  # re-export for callers that import from this module
