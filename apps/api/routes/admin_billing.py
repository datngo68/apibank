"""Admin billing — subscriptions + invoices actions.

Phase 3. Mọi endpoint require admin/owner; mutation đều audit.
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.billing import wallet
from packages.db.models import Invoice, Plan, Subscription, User
from packages.db.session import get_session
from packages.schemas.auth import GenericMessage
from packages.security.audit import record_audit
from packages.security.user_auth import current_admin_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/admin", tags=["admin-billing"])


def _sub_dict(s: Subscription, plan_code: str | None, user_email: str | None) -> dict[str, Any]:
    return {
        "id": s.id,
        "user_id": s.user_id,
        "user_email": user_email,
        "plan_id": s.plan_id,
        "plan_code": plan_code,
        "status": s.status,
        "started_at": s.started_at.isoformat(),
        "expires_at": s.expires_at.isoformat(),
        "auto_renew": s.auto_renew,
        "created_at": s.created_at.isoformat(),
    }


@router.get("/subscriptions")
async def admin_list_subscriptions(
    status_filter: str | None = Query(default=None, alias="status"),
    plan_code: str | None = None,
    user_id: str | None = None,
    expiring_in_days: int | None = Query(default=None, ge=0, le=365),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    stmt = (
        select(Subscription, Plan.code, User.email)
        .outerjoin(Plan, Plan.id == Subscription.plan_id)
        .outerjoin(User, User.id == Subscription.user_id)
    )
    count_stmt = select(func.count()).select_from(Subscription)
    if status_filter:
        stmt = stmt.where(Subscription.status == status_filter)
        count_stmt = count_stmt.where(Subscription.status == status_filter)
    if plan_code:
        plan = (
            await session.scalars(select(Plan).where(Plan.code == plan_code))
        ).first()
        if plan is not None:
            stmt = stmt.where(Subscription.plan_id == plan.id)
            count_stmt = count_stmt.where(Subscription.plan_id == plan.id)
    if user_id:
        stmt = stmt.where(Subscription.user_id == user_id)
        count_stmt = count_stmt.where(Subscription.user_id == user_id)
    if expiring_in_days is not None:
        cutoff = datetime.now(UTC) + timedelta(days=expiring_in_days)
        stmt = stmt.where(Subscription.expires_at <= cutoff).where(
            Subscription.status == "active"
        )
        count_stmt = count_stmt.where(Subscription.expires_at <= cutoff).where(
            Subscription.status == "active"
        )
    total = int((await session.execute(count_stmt)).scalar_one() or 0)
    stmt = stmt.order_by(desc(Subscription.expires_at)).limit(limit).offset(offset)
    rows = (await session.execute(stmt)).all()
    return {
        "items": [_sub_dict(s, code, email) for s, code, email in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/subscriptions/{sub_id}:cancel", response_model=GenericMessage)
async def admin_cancel_sub(
    sub_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    sub = await session.get(Subscription, sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="not found")
    before = {"status": sub.status, "auto_renew": sub.auto_renew}
    sub.status = "canceled"
    sub.auto_renew = False
    await record_audit(
        session,
        actor=actor.id,
        action="admin.sub.cancel",
        target_type="subscription",
        target_id=sub.id,
        ip=request.client.host if request.client else None,
        before=before,
        after={"status": "canceled"},
    )
    await session.commit()
    return GenericMessage(message="canceled")


@router.post("/subscriptions/{sub_id}:extend", response_model=GenericMessage)
async def admin_extend_sub(
    sub_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
    days: int = Query(..., ge=1, le=365),
) -> GenericMessage:
    sub = await session.get(Subscription, sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="not found")
    before = {"expires_at": sub.expires_at.isoformat()}
    sub.expires_at = sub.expires_at + timedelta(days=days)
    if sub.status in ("expired", "canceled"):
        sub.status = "active"
    await record_audit(
        session,
        actor=actor.id,
        action="admin.sub.extend",
        target_type="subscription",
        target_id=sub.id,
        ip=request.client.host if request.client else None,
        before=before,
        after={"expires_at": sub.expires_at.isoformat(), "days": days},
    )
    await session.commit()
    return GenericMessage(message=f"extended {days} days")


@router.post("/subscriptions/{sub_id}:change-plan", response_model=GenericMessage)
async def admin_change_plan(
    sub_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
    plan_code: str = Query(..., min_length=1, max_length=32),
    reset_period: bool = Query(default=False),
) -> GenericMessage:
    sub = await session.get(Subscription, sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="not found")
    plan = (
        await session.scalars(select(Plan).where(Plan.code == plan_code))
    ).first()
    if plan is None:
        raise HTTPException(status_code=404, detail="plan not found")
    before = {"plan_id": sub.plan_id, "expires_at": sub.expires_at.isoformat()}
    sub.plan_id = plan.id
    if reset_period:
        sub.started_at = datetime.now(UTC)
        sub.expires_at = sub.started_at + timedelta(days=plan.duration_days)
        sub.status = "active"
    await record_audit(
        session,
        actor=actor.id,
        action="admin.sub.change_plan",
        target_type="subscription",
        target_id=sub.id,
        ip=request.client.host if request.client else None,
        before=before,
        after={
            "plan_id": plan.id,
            "plan_code": plan.code,
            "reset_period": reset_period,
        },
    )
    await session.commit()
    return GenericMessage(message=f"changed to {plan.code}")


@router.patch("/subscriptions/{sub_id}", response_model=GenericMessage)
async def admin_update_sub(
    sub_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
    auto_renew: bool | None = None,
) -> GenericMessage:
    sub = await session.get(Subscription, sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="not found")
    before = {"auto_renew": sub.auto_renew}
    if auto_renew is not None:
        sub.auto_renew = auto_renew
    await record_audit(
        session,
        actor=actor.id,
        action="admin.sub.update",
        target_type="subscription",
        target_id=sub.id,
        ip=request.client.host if request.client else None,
        before=before,
        after={"auto_renew": sub.auto_renew},
    )
    await session.commit()
    return GenericMessage(message="ok")


@router.post("/subscriptions/{sub_id}:refund", response_model=GenericMessage)
async def admin_refund_sub(
    sub_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
    amount_vnd: int | None = Query(default=None, ge=1),
    note: str = Query(default="admin refund subscription", max_length=500),
) -> GenericMessage:
    """Refund + cancel + void invoice gần nhất.

    Nếu amount không truyền, dùng `amount_vnd` của invoice paid mới nhất gắn
    với sub. Đẩy về ví user qua wallet.refund + chuyển sub status='canceled'.
    """
    sub = await session.get(Subscription, sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="not found")
    invoice = (
        await session.scalars(
            select(Invoice)
            .where(Invoice.subscription_id == sub.id)
            .where(Invoice.status == "paid")
            .order_by(desc(Invoice.issued_at))
            .limit(1)
        )
    ).first()
    refund_amount = Decimal(amount_vnd) if amount_vnd else (
        Decimal(invoice.amount_vnd) if invoice is not None else Decimal(0)
    )
    if refund_amount <= 0:
        raise HTTPException(
            status_code=400, detail="refund_amount phải > 0 (truyền amount_vnd)"
        )
    idem = f"admin-refund-sub:{sub.id}:{secrets.token_hex(6)}"
    await wallet.refund(
        session,
        user_id=sub.user_id,
        amount_vnd=refund_amount,
        idempotency_key=idem,
        ref_kind="admin_refund_sub",
        ref_id=sub.id,
        note=note,
        created_by=f"admin:{actor.email}",
    )
    sub.status = "canceled"
    sub.auto_renew = False
    if invoice is not None:
        invoice.status = "void"
    await record_audit(
        session,
        actor=actor.id,
        action="admin.sub.refund",
        target_type="subscription",
        target_id=sub.id,
        ip=request.client.host if request.client else None,
        after={
            "amount_vnd": int(refund_amount),
            "voided_invoice_id": invoice.id if invoice else None,
        },
    )
    await session.commit()
    return GenericMessage(message=f"refunded {int(refund_amount)} VND")


# ---------------------------------------------------------------------------
# INVOICES ACTIONS
# ---------------------------------------------------------------------------


@router.post("/invoices/{invoice_id}:void", response_model=GenericMessage)
async def admin_void_invoice(
    invoice_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    inv = await session.get(Invoice, invoice_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="not found")
    before = {"status": inv.status}
    inv.status = "void"
    await record_audit(
        session,
        actor=actor.id,
        action="admin.invoice.void",
        target_type="invoice",
        target_id=inv.id,
        ip=request.client.host if request.client else None,
        before=before,
        after={"status": "void"},
    )
    await session.commit()
    return GenericMessage(message="void")


@router.post("/invoices/{invoice_id}:mark-paid", response_model=GenericMessage)
async def admin_mark_invoice_paid(
    invoice_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    inv = await session.get(Invoice, invoice_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="not found")
    before = {"status": inv.status}
    inv.status = "paid"
    await record_audit(
        session,
        actor=actor.id,
        action="admin.invoice.mark_paid",
        target_type="invoice",
        target_id=inv.id,
        ip=request.client.host if request.client else None,
        before=before,
        after={"status": "paid"},
    )
    await session.commit()
    return GenericMessage(message="paid")


@router.post("/invoices/{invoice_id}:regenerate-pdf", response_model=GenericMessage)
async def admin_regenerate_invoice_pdf(
    invoice_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    """Sinh lại PDF (ghi vào ``pdf_path``).

    Helper :mod:`packages.billing.invoice_pdf` lazy-import để tránh hard
    dependency với reportlab khi chưa cài.
    """
    from packages.billing import invoice_pdf

    inv = await session.get(Invoice, invoice_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="not found")
    user = await session.get(User, inv.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="invoice user missing")
    try:
        path = await invoice_pdf.generate(inv, user)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"pdf gen failed: {exc}") from exc
    inv.pdf_path = path
    await record_audit(
        session,
        actor=actor.id,
        action="admin.invoice.regenerate_pdf",
        target_type="invoice",
        target_id=inv.id,
        ip=request.client.host if request.client else None,
        after={"pdf_path": path},
    )
    await session.commit()
    return GenericMessage(message="generated")


@router.post("/invoices/{invoice_id}:resend-email", response_model=GenericMessage)
async def admin_resend_invoice_email(
    invoice_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    inv = await session.get(Invoice, invoice_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="not found")
    user = await session.get(User, inv.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="invoice user missing")
    from packages.notifications import email as email_pkg

    body = (
        f"Hoá đơn {inv.id} ({inv.plan_code or '—'}) — {int(inv.amount_vnd):,} VND.\n"
        f"Status: {inv.status}. Cấp lại theo yêu cầu."
    )
    await email_pkg.send_email(
        to=user.email,
        subject=f"APIBank · Hoá đơn {inv.id}",
        body=body,
        session=session,
    )
    await record_audit(
        session,
        actor=actor.id,
        action="admin.invoice.resend_email",
        target_type="invoice",
        target_id=inv.id,
        ip=request.client.host if request.client else None,
        after={"to": user.email},
    )
    await session.commit()
    return GenericMessage(message="sent")


@router.get("/invoices/export.csv")
async def admin_invoices_export_csv(
    user_id: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    plan_code: str | None = None,
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Export filter invoices ra CSV (StreamingResponse)."""
    import csv
    import io
    from collections.abc import AsyncIterator

    from fastapi.responses import StreamingResponse

    stmt = select(Invoice, User.email).outerjoin(User, User.id == Invoice.user_id)
    if user_id:
        stmt = stmt.where(Invoice.user_id == user_id)
    if status_filter:
        stmt = stmt.where(Invoice.status == status_filter)
    if plan_code:
        stmt = stmt.where(Invoice.plan_code == plan_code)
    if date_from:
        stmt = stmt.where(Invoice.issued_at >= date_from)
    if date_to:
        stmt = stmt.where(Invoice.issued_at <= date_to)

    async def _gen() -> AsyncIterator[bytes]:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "id",
                "user_email",
                "plan_code",
                "amount_vnd",
                "currency",
                "status",
                "coupon_code",
                "discount_vnd",
                "issued_at",
            ]
        )
        yield buf.getvalue().encode("utf-8")
        buf.seek(0)
        buf.truncate(0)

        rows = (await session.execute(stmt.order_by(desc(Invoice.issued_at)))).all()
        for inv, email in rows:
            writer.writerow(
                [
                    inv.id,
                    email or "",
                    inv.plan_code or "",
                    int(inv.amount_vnd),
                    inv.currency,
                    inv.status,
                    inv.coupon_code or "",
                    int(inv.discount_vnd or 0),
                    inv.issued_at.isoformat(),
                ]
            )
            yield buf.getvalue().encode("utf-8")
            buf.seek(0)
            buf.truncate(0)

    return StreamingResponse(
        _gen(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=invoices.csv"},
    )


__all__ = ["router"]
