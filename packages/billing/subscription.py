"""Subscription + Invoice.

Logic:
- `purchase(user, plan)` debit ví → upsert Subscription (extend nếu đang còn) →
  tạo Invoice paid → trả (subscription, invoice).
- `expire_due_subscriptions()` job: chạy hằng ngày, đánh dấu expired và (tùy chọn)
  notify trước 3 ngày + ngày hết hạn.
- Idempotency: client gửi `idempotency_key` để retry an toàn.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from packages.billing import wallet
from packages.billing.errors import PlanNotFoundError
from packages.db.models import Invoice, Plan, Subscription, User


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


async def get_active_subscription(
    session: AsyncSession, user_id: str
) -> Subscription | None:
    stmt = (
        select(Subscription)
        .where(Subscription.user_id == user_id)
        .where(Subscription.status == "active")
        .order_by(Subscription.expires_at.desc())
    )
    sub = (await session.scalars(stmt)).first()
    if sub is None:
        return None
    expires = _aware(sub.expires_at)
    if expires is None or expires < datetime.now(UTC):
        return None
    return sub


async def get_plan(session: AsyncSession, code: str) -> Plan:
    plan = (
        await session.scalars(select(Plan).where(Plan.code == code).where(Plan.active.is_(True)))
    ).first()
    if plan is None:
        raise PlanNotFoundError(f"plan {code!r} not found or inactive")
    return plan


async def purchase(
    session: AsyncSession,
    *,
    user: User,
    plan_code: str,
    idempotency_key: str | None = None,
) -> tuple[Subscription, Invoice]:
    """Mua/gia hạn gói. Caller phải `commit()`.

    - Debit ví theo `plan.price_vnd` (idempotency_key duy nhất per purchase).
    - Nếu user đã có Subscription active của bất kỳ plan nào → extend `expires_at`
      thêm `plan.duration_days` từ thời điểm hết hạn hiện tại.
    - Invoice luôn được tạo (status=paid).
    """
    plan = await get_plan(session, plan_code)
    key = idempotency_key or f"sub:{user.id}:{plan.code}:{int(datetime.now(UTC).timestamp())}"

    # Debit ví trước; nếu thiếu sẽ raise InsufficientFundsError, caller xử lý.
    wallet_tx = await wallet.debit(
        session,
        user_id=user.id,
        amount_vnd=Decimal(plan.price_vnd),
        idempotency_key=key,
        ref_kind="invoice",
        note=f"Mua gói {plan.code}",
        created_by=user.id,
    )

    now = datetime.now(UTC)
    duration = timedelta(days=plan.duration_days)

    existing = await get_active_subscription(session, user.id)
    if existing is not None:
        current_exp = _aware(existing.expires_at) or now
        existing.expires_at = current_exp + duration
        existing.plan_id = plan.id
        existing.status = "active"
        sub = existing
    else:
        sub = Subscription(
            user_id=user.id,
            plan_id=plan.id,
            started_at=now,
            expires_at=now + duration,
            status="active",
        )
        session.add(sub)
        await session.flush()

    invoice = Invoice(
        user_id=user.id,
        subscription_id=sub.id,
        plan_code=plan.code,
        amount_vnd=Decimal(plan.price_vnd),
        currency="VND",
        status="paid",
        wallet_tx_id=wallet_tx.id,
        issued_at=now,
    )
    session.add(invoice)
    await session.flush()
    # Best-effort notify; không fail purchase nếu dispatcher lỗi.
    try:
        from packages.notifications.dispatcher import notify

        await notify(
            session,
            user=user,
            kind="subscription_purchased",
            title=f"Đã kích hoạt gói {plan.code}",
            body=(
                f"Hoá đơn {invoice.id} đã thanh toán {int(plan.price_vnd):,} VND. "
                f"Hết hạn: {sub.expires_at.isoformat(timespec='minutes')}."
            ),
            payload={
                "invoice_id": invoice.id,
                "subscription_id": sub.id,
                "plan_code": plan.code,
                "amount_vnd": int(plan.price_vnd),
                "expires_at": sub.expires_at.isoformat(),
            },
        )
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).exception(
            "notify_subscription_purchased_failed", extra={"sub": sub.id}
        )
    return sub, invoice


async def change_plan(
    session: AsyncSession,
    *,
    user: User,
    new_plan_code: str,
    idempotency_key: str | None = None,
) -> tuple[Subscription, Invoice]:
    """Đổi sang gói khác. Tính theo nguyên tắc đơn giản: tính tỉ lệ thời gian còn lại
    của gói hiện tại quy đổi thành VND, refund lại ví, rồi mua plan mới.

    Để đơn giản hóa, ta chỉ tính refund nếu có subscription đang active.
    """
    existing = await get_active_subscription(session, user.id)
    refund_key_suffix = idempotency_key or f"{user.id}:{new_plan_code}:{int(datetime.now(UTC).timestamp())}"

    if existing is not None:
        current_plan = await session.get(Plan, existing.plan_id)
        if current_plan is not None:
            now = datetime.now(UTC)
            total_days = max(1, current_plan.duration_days)
            remaining = max(timedelta(0), (_aware(existing.expires_at) or now) - now)
            refund_amount = (
                Decimal(current_plan.price_vnd) * Decimal(remaining.days) / Decimal(total_days)
            )
            refund_amount = refund_amount.quantize(Decimal(1))
            if refund_amount > 0:
                await wallet.refund(
                    session,
                    user_id=user.id,
                    amount_vnd=refund_amount,
                    idempotency_key=f"prorate:{refund_key_suffix}",
                    ref_kind="subscription",
                    ref_id=existing.id,
                    note=f"Hoàn tiền tỉ lệ gói {current_plan.code}",
                    created_by=user.id,
                )
            existing.status = "canceled"

    return await purchase(
        session,
        user=user,
        plan_code=new_plan_code,
        idempotency_key=f"change:{refund_key_suffix}",
    )


async def expire_due_subscriptions(session: AsyncSession) -> int:
    """Đánh dấu các sub đã hết hạn nhưng chưa cập nhật. Trả số bản ghi đã đổi."""
    now = datetime.now(UTC)
    result = await session.execute(
        update(Subscription)
        .where(Subscription.status == "active")
        .where(Subscription.expires_at < now)
        .values(status="expired")
    )
    return int(result.rowcount or 0)


async def list_invoices(
    session: AsyncSession, user_id: str, *, limit: int = 50
) -> list[Invoice]:
    rows = list(
        (
            await session.scalars(
                select(Invoice)
                .where(Invoice.user_id == user_id)
                .order_by(Invoice.issued_at.desc())
                .limit(limit)
            )
        ).all()
    )
    return rows


async def has_active_subscription(session: AsyncSession, user_id: str) -> bool:
    return (await get_active_subscription(session, user_id)) is not None
