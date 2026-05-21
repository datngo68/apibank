"""Admin operations cho Order, Transaction, Webhook (cross-user, vận hành).

Phase 2 — Admin operational core. Mọi endpoint require role admin/owner +
audit mọi mutation.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.billing import wallet
from packages.db.models import (
    BankAccount,
    Order,
    Transaction,
    User,
    Webhook,
    WebhookAttempt,
)
from packages.db.session import get_session
from packages.schemas.auth import GenericMessage
from packages.security.audit import record_audit
from packages.security.user_auth import current_admin_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/admin", tags=["admin-ops"])


# ---------------------------------------------------------------------------
# ORDERS
# ---------------------------------------------------------------------------


def _order_dict(order: Order, *, user_email: str | None) -> dict[str, Any]:
    return {
        "id": order.id,
        "code": order.code,
        "amount_vnd": str(order.amount_vnd),
        "status": order.status,
        "bank_account_id": order.bank_account_id,
        "user_id": order.user_id,
        "user_email": user_email,
        "description": order.description,
        "customer_ref": order.customer_ref,
        "expired_at": order.expired_at.isoformat(),
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        "paid_tx_id": order.paid_tx_id,
        "metadata_json": order.metadata_json or {},
        "created_at": order.created_at.isoformat(),
    }


@router.get("/orders")
async def admin_list_orders(
    q: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    user_id: str | None = None,
    bank_account_id: str | None = None,
    customer_ref: str | None = None,
    amount_min: int | None = None,
    amount_max: int | None = None,
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    stmt = select(Order, User.email).outerjoin(User, User.id == Order.user_id)
    count_stmt = select(func.count()).select_from(Order)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(Order.code.ilike(like), Order.description.ilike(like))
        )
        count_stmt = count_stmt.where(
            or_(Order.code.ilike(like), Order.description.ilike(like))
        )
    if status_filter:
        stmt = stmt.where(Order.status == status_filter)
        count_stmt = count_stmt.where(Order.status == status_filter)
    if user_id:
        stmt = stmt.where(Order.user_id == user_id)
        count_stmt = count_stmt.where(Order.user_id == user_id)
    if bank_account_id:
        stmt = stmt.where(Order.bank_account_id == bank_account_id)
        count_stmt = count_stmt.where(Order.bank_account_id == bank_account_id)
    if customer_ref:
        stmt = stmt.where(Order.customer_ref == customer_ref)
        count_stmt = count_stmt.where(Order.customer_ref == customer_ref)
    if amount_min is not None:
        stmt = stmt.where(Order.amount_vnd >= amount_min)
        count_stmt = count_stmt.where(Order.amount_vnd >= amount_min)
    if amount_max is not None:
        stmt = stmt.where(Order.amount_vnd <= amount_max)
        count_stmt = count_stmt.where(Order.amount_vnd <= amount_max)
    if date_from:
        stmt = stmt.where(Order.created_at >= date_from)
        count_stmt = count_stmt.where(Order.created_at >= date_from)
    if date_to:
        stmt = stmt.where(Order.created_at <= date_to)
        count_stmt = count_stmt.where(Order.created_at <= date_to)

    total = int((await session.execute(count_stmt)).scalar_one() or 0)
    stmt = stmt.order_by(desc(Order.created_at)).limit(limit).offset(offset)
    rows = (await session.execute(stmt)).all()
    items = [_order_dict(o, user_email=email) for o, email in rows]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/orders/{order_id}")
async def admin_order_detail(
    order_id: str,
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    order = await session.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    user_email = None
    if order.user_id:
        user = await session.get(User, order.user_id)
        user_email = user.email if user else None

    matched_tx = None
    if order.paid_tx_id:
        tx = await session.get(Transaction, order.paid_tx_id)
        if tx is not None:
            matched_tx = {
                "id": tx.id,
                "bank_ref_no": tx.bank_ref_no,
                "amount_vnd": str(tx.amount_vnd),
                "content": tx.content,
                "posted_at": tx.posted_at.isoformat(),
                "state": tx.state,
            }

    attempts = list(
        (
            await session.scalars(
                select(WebhookAttempt)
                .where(WebhookAttempt.order_id == order_id)
                .order_by(desc(WebhookAttempt.next_run_at))
            )
        ).all()
    )
    attempt_payload = [
        {
            "id": a.id,
            "webhook_id": a.webhook_id,
            "status": a.status,
            "attempt": a.attempt,
            "max_attempts": a.max_attempts,
            "last_status_code": a.last_status_code,
            "last_error": a.last_error,
            "next_run_at": a.next_run_at.isoformat(),
            "sent_at": a.sent_at.isoformat() if a.sent_at else None,
        }
        for a in attempts
    ]

    return {
        **_order_dict(order, user_email=user_email),
        "matched_transaction": matched_tx,
        "webhook_attempts": attempt_payload,
    }


@router.post("/orders/{order_id}:cancel", response_model=GenericMessage)
async def admin_cancel_order(
    order_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    order = await session.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    if order.status not in ("pending",):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"order status='{order.status}' không thể hủy",
        )
    before = {"status": order.status}
    order.status = "canceled"
    order.updated_at = datetime.now(UTC)
    await record_audit(
        session,
        actor=actor.id,
        action="admin.order.cancel",
        target_type="order",
        target_id=order.id,
        ip=request.client.host if request.client else None,
        before=before,
        after={"status": order.status},
    )
    await session.commit()
    return GenericMessage(message="canceled")


@router.post("/orders/{order_id}:force-match", response_model=GenericMessage)
async def admin_force_match_order(
    order_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
    tx_id: str = Query(..., description="Transaction id để gắn vào order"),
) -> GenericMessage:
    order = await session.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    tx = await session.get(Transaction, tx_id)
    if tx is None:
        raise HTTPException(status_code=404, detail="transaction not found")
    if tx.bank_account_id != order.bank_account_id:
        raise HTTPException(
            status_code=400,
            detail="transaction phải cùng bank_account với order",
        )
    before = {"status": order.status, "paid_tx_id": order.paid_tx_id}
    order.status = "paid"
    order.paid_tx_id = tx.id
    order.paid_at = datetime.now(UTC)
    tx.state = "matched"
    tx.matched_order_id = order.id
    await record_audit(
        session,
        actor=actor.id,
        action="admin.order.force_match",
        target_type="order",
        target_id=order.id,
        ip=request.client.host if request.client else None,
        before=before,
        after={"status": "paid", "paid_tx_id": tx.id},
    )
    await session.commit()
    return GenericMessage(message="matched")


# ---------------------------------------------------------------------------
# TRANSACTIONS
# ---------------------------------------------------------------------------


def _tx_dict(tx: Transaction) -> dict[str, Any]:
    return {
        "id": tx.id,
        "bank_account_id": tx.bank_account_id,
        "bank_ref_no": tx.bank_ref_no,
        "amount_vnd": str(tx.amount_vnd),
        "content": tx.content,
        "state": tx.state,
        "matched_order_id": tx.matched_order_id,
        "posted_at": tx.posted_at.isoformat(),
        "inserted_at": tx.inserted_at.isoformat(),
    }


@router.get("/transactions")
async def admin_list_transactions(
    q: str | None = None,
    state: str | None = None,
    bank_account_id: str | None = None,
    bank_ref_no: str | None = None,
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    stmt = select(Transaction)
    count_stmt = select(func.count()).select_from(Transaction)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Transaction.content.ilike(like))
        count_stmt = count_stmt.where(Transaction.content.ilike(like))
    if state:
        stmt = stmt.where(Transaction.state == state)
        count_stmt = count_stmt.where(Transaction.state == state)
    if bank_account_id:
        stmt = stmt.where(Transaction.bank_account_id == bank_account_id)
        count_stmt = count_stmt.where(Transaction.bank_account_id == bank_account_id)
    if bank_ref_no:
        stmt = stmt.where(Transaction.bank_ref_no == bank_ref_no)
        count_stmt = count_stmt.where(Transaction.bank_ref_no == bank_ref_no)
    if date_from:
        stmt = stmt.where(Transaction.posted_at >= date_from)
        count_stmt = count_stmt.where(Transaction.posted_at >= date_from)
    if date_to:
        stmt = stmt.where(Transaction.posted_at <= date_to)
        count_stmt = count_stmt.where(Transaction.posted_at <= date_to)

    total = int((await session.execute(count_stmt)).scalar_one() or 0)
    stmt = stmt.order_by(desc(Transaction.posted_at)).limit(limit).offset(offset)
    rows = list((await session.scalars(stmt)).all())
    return {
        "items": [_tx_dict(t) for t in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/transactions/{tx_id}")
async def admin_transaction_detail(
    tx_id: str,
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    tx = await session.get(Transaction, tx_id)
    if tx is None:
        raise HTTPException(status_code=404, detail="not found")
    body = _tx_dict(tx)
    body["raw_json"] = tx.raw_json or {}
    return body


@router.post("/transactions/{tx_id}:reject", response_model=GenericMessage)
async def admin_reject_transaction(
    tx_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    tx = await session.get(Transaction, tx_id)
    if tx is None:
        raise HTTPException(status_code=404, detail="not found")
    before = {"state": tx.state}
    tx.state = "rejected"
    tx.matched_order_id = None
    await record_audit(
        session,
        actor=actor.id,
        action="admin.tx.reject",
        target_type="transaction",
        target_id=tx.id,
        ip=request.client.host if request.client else None,
        before=before,
        after={"state": tx.state},
    )
    await session.commit()
    return GenericMessage(message="rejected")


@router.post("/transactions/{tx_id}:match", response_model=GenericMessage)
async def admin_match_transaction(
    tx_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
    order_id: str = Query(..., description="Order id để gắn"),
) -> GenericMessage:
    tx = await session.get(Transaction, tx_id)
    if tx is None:
        raise HTTPException(status_code=404, detail="not found")
    order = await session.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    if order.bank_account_id != tx.bank_account_id:
        raise HTTPException(
            status_code=400,
            detail="bank_account của tx và order phải khớp",
        )
    before = {"state": tx.state, "matched_order_id": tx.matched_order_id}
    tx.state = "matched"
    tx.matched_order_id = order.id
    if order.status == "pending":
        order.status = "paid"
        order.paid_tx_id = tx.id
        order.paid_at = datetime.now(UTC)
    await record_audit(
        session,
        actor=actor.id,
        action="admin.tx.match",
        target_type="transaction",
        target_id=tx.id,
        ip=request.client.host if request.client else None,
        before=before,
        after={"state": tx.state, "matched_order_id": order.id},
    )
    await session.commit()
    return GenericMessage(message="matched")


@router.post("/transactions/{tx_id}:rematch", response_model=GenericMessage)
async def admin_rematch_transaction(
    tx_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    """Chạy lại matcher cho 1 transaction (rất ít khi cần — debug only)."""
    from packages.core.matcher import (
        MatchCandidate,
        MatchInput,
        find_order_match,
    )

    tx = await session.get(Transaction, tx_id)
    if tx is None:
        raise HTTPException(status_code=404, detail="not found")

    pending = list(
        (
            await session.scalars(
                select(Order)
                .where(Order.bank_account_id == tx.bank_account_id)
                .where(Order.status == "pending")
            )
        ).all()
    )
    candidates = [
        MatchCandidate(
            id=o.id,
            code=o.code,
            amount=Decimal(o.amount_vnd),
            status="pending",
            expired_at=o.expired_at,
        )
        for o in pending
    ]
    result = find_order_match(
        MatchInput(amount=Decimal(tx.amount_vnd), content=tx.content),
        candidates,
    )
    if result.status == "matched" and result.order_id:
        matched = await session.get(Order, result.order_id)
        if matched is not None:
            before = {"state": tx.state, "matched_order_id": tx.matched_order_id}
            tx.state = "matched"
            tx.matched_order_id = matched.id
            if matched.status == "pending":
                matched.status = "paid"
                matched.paid_tx_id = tx.id
                matched.paid_at = datetime.now(UTC)
            await record_audit(
                session,
                actor=actor.id,
                action="admin.tx.rematch",
                target_type="transaction",
                target_id=tx.id,
                ip=request.client.host if request.client else None,
                before=before,
                after={"state": tx.state, "matched_order_id": matched.id},
            )
            await session.commit()
            return GenericMessage(message=f"matched to {matched.id}")
    return GenericMessage(message=f"no_match: {result.status}")


@router.post("/transactions/{tx_id}:refund", response_model=GenericMessage)
async def admin_refund_transaction(
    tx_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
    note: str = Query(default="admin refund", max_length=500),
) -> GenericMessage:
    """Refund 1 transaction → cộng lại ví user nếu order là topup."""
    import secrets as _secrets

    tx = await session.get(Transaction, tx_id)
    if tx is None:
        raise HTTPException(status_code=404, detail="not found")
    if not tx.matched_order_id:
        raise HTTPException(
            status_code=400, detail="tx chưa match order, không có target để refund"
        )
    order = await session.get(Order, tx.matched_order_id)
    if order is None or not order.user_id:
        raise HTTPException(
            status_code=400, detail="order không có user → không refund được"
        )
    idem = f"admin-refund-tx:{tx.id}:{_secrets.token_hex(6)}"
    await wallet.refund(
        session,
        user_id=order.user_id,
        amount_vnd=Decimal(tx.amount_vnd),
        idempotency_key=idem,
        ref_kind="admin_refund_tx",
        ref_id=tx.id,
        note=note,
        created_by=f"admin:{actor.email}",
    )
    tx.state = "refunded"
    order.status = "refunded"
    await record_audit(
        session,
        actor=actor.id,
        action="admin.tx.refund",
        target_type="transaction",
        target_id=tx.id,
        ip=request.client.host if request.client else None,
        after={"amount_vnd": str(tx.amount_vnd), "user_id": order.user_id},
    )
    await session.commit()
    return GenericMessage(message="refunded")


# ---------------------------------------------------------------------------
# WEBHOOKS (cross-user) + WEBHOOK ATTEMPTS (DLQ)
# ---------------------------------------------------------------------------


def _webhook_dict(wh: Webhook, *, user_email: str | None) -> dict[str, Any]:
    return {
        "id": wh.id,
        "owner_id": wh.owner_id,
        "user_id": wh.user_id,
        "user_email": user_email,
        "name": wh.name,
        "url": wh.url,
        "active": wh.active,
        "events_json": wh.events_json or {},
        "headers_json": wh.headers_json or {},
        "ip_allowlist": wh.ip_allowlist,
        "last_delivery_at": (
            wh.last_delivery_at.isoformat() if wh.last_delivery_at else None
        ),
        "created_at": wh.created_at.isoformat(),
    }


@router.get("/webhooks")
async def admin_list_webhooks(
    user_id: str | None = None,
    active: bool | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    stmt = select(Webhook, User.email).outerjoin(User, User.id == Webhook.user_id)
    count_stmt = select(func.count()).select_from(Webhook)
    if user_id:
        stmt = stmt.where(Webhook.user_id == user_id)
        count_stmt = count_stmt.where(Webhook.user_id == user_id)
    if active is not None:
        stmt = stmt.where(Webhook.active.is_(active))
        count_stmt = count_stmt.where(Webhook.active.is_(active))
    total = int((await session.execute(count_stmt)).scalar_one() or 0)
    stmt = stmt.order_by(desc(Webhook.created_at)).limit(limit).offset(offset)
    rows = (await session.execute(stmt)).all()
    return {
        "items": [_webhook_dict(w, user_email=email) for w, email in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.patch("/webhooks/{webhook_id}", response_model=GenericMessage)
async def admin_update_webhook(
    webhook_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
    active: bool | None = None,
) -> GenericMessage:
    wh = await session.get(Webhook, webhook_id)
    if wh is None:
        raise HTTPException(status_code=404, detail="not found")
    before = {"active": wh.active}
    if active is not None:
        wh.active = active
    await record_audit(
        session,
        actor=actor.id,
        action="admin.webhook.update",
        target_type="webhook",
        target_id=wh.id,
        ip=request.client.host if request.client else None,
        before=before,
        after={"active": wh.active},
    )
    await session.commit()
    return GenericMessage(message="ok")


@router.get("/webhook-attempts")
async def admin_list_webhook_attempts(
    status_filter: str | None = Query(default=None, alias="status"),
    webhook_id: str | None = None,
    order_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    stmt = select(WebhookAttempt)
    count_stmt = select(func.count()).select_from(WebhookAttempt)
    if status_filter:
        stmt = stmt.where(WebhookAttempt.status == status_filter)
        count_stmt = count_stmt.where(WebhookAttempt.status == status_filter)
    if webhook_id:
        stmt = stmt.where(WebhookAttempt.webhook_id == webhook_id)
        count_stmt = count_stmt.where(WebhookAttempt.webhook_id == webhook_id)
    if order_id:
        stmt = stmt.where(WebhookAttempt.order_id == order_id)
        count_stmt = count_stmt.where(WebhookAttempt.order_id == order_id)

    total = int((await session.execute(count_stmt)).scalar_one() or 0)
    stmt = stmt.order_by(desc(WebhookAttempt.next_run_at)).limit(limit).offset(offset)
    rows = list((await session.scalars(stmt)).all())
    items = [
        {
            "id": a.id,
            "webhook_id": a.webhook_id,
            "order_id": a.order_id,
            "transaction_id": a.transaction_id,
            "status": a.status,
            "attempt": a.attempt,
            "max_attempts": a.max_attempts,
            "last_status_code": a.last_status_code,
            "last_error": a.last_error,
            "next_run_at": a.next_run_at.isoformat(),
            "sent_at": a.sent_at.isoformat() if a.sent_at else None,
            "claimed_at": a.claimed_at.isoformat() if a.claimed_at else None,
        }
        for a in rows
    ]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("/webhook-attempts/{attempt_id}:replay", response_model=GenericMessage)
async def admin_replay_attempt(
    attempt_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    """Reset attempt = 0 và đẩy về pending để dispatcher pick lại."""
    a = await session.get(WebhookAttempt, attempt_id)
    if a is None:
        raise HTTPException(status_code=404, detail="not found")
    a.status = "pending"
    a.attempt = 0
    a.next_run_at = datetime.now(UTC)
    a.claimed_at = None
    a.last_error = None
    await record_audit(
        session,
        actor=actor.id,
        action="admin.webhook_attempt.replay",
        target_type="webhook_attempt",
        target_id=a.id,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return GenericMessage(message="replaying")


@router.post("/webhook-attempts/{attempt_id}:redeliver", response_model=GenericMessage)
async def admin_redeliver_attempt(
    attempt_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    """Giữ attempt count, chỉ đẩy next_run_at về now."""
    a = await session.get(WebhookAttempt, attempt_id)
    if a is None:
        raise HTTPException(status_code=404, detail="not found")
    if a.status == "delivered":
        raise HTTPException(status_code=400, detail="already delivered")
    a.status = "pending"
    a.next_run_at = datetime.now(UTC)
    a.claimed_at = None
    await record_audit(
        session,
        actor=actor.id,
        action="admin.webhook_attempt.redeliver",
        target_type="webhook_attempt",
        target_id=a.id,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return GenericMessage(message="redelivering")


@router.post("/webhook-attempts/cleanup", response_model=GenericMessage)
async def admin_cleanup_webhook_attempts(
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    """Reset orphan dispatching > 5 phút (nếu scheduler stuck/crash)."""
    from packages.webhook.dispatcher import reset_stuck_dispatching

    n = await reset_stuck_dispatching(session)
    await record_audit(
        session,
        actor=actor.id,
        action="admin.webhook_attempt.cleanup",
        target_type="webhook_attempt",
        target_id="*",
        ip=request.client.host if request.client else None,
        after={"reset": n},
    )
    await session.commit()
    return GenericMessage(message=f"reset {n} stuck attempts")


# Suppress unused warnings on imports tracked statically.
_ = (BankAccount,)


__all__ = ["router"]
