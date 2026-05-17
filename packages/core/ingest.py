from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from packages.banks.base import BankTransaction
from packages.core.matcher import (
    MatchCandidate,
    MatchInput,
    OrderStatus,
    find_order_match,
)
from packages.core.state_machine import transition_order
from packages.db.models import Order, Transaction, Webhook, WebhookAttempt, utcnow
from packages.obs import metrics

logger = logging.getLogger(__name__)


async def ingest_transaction(
    session: AsyncSession,
    *,
    bank_account_id: str,
    bank_transaction: BankTransaction,
) -> Transaction:
    existing = (
        await session.scalars(
            select(Transaction).where(
                Transaction.bank_account_id == bank_account_id,
                Transaction.bank_ref_no == bank_transaction.bank_ref_no,
            )
        )
    ).first()
    if existing is not None:
        return existing

    with metrics.ingest_critical_path_seconds.time():
        transaction = Transaction(
            bank_account_id=bank_account_id,
            bank_ref_no=bank_transaction.bank_ref_no,
            amount_vnd=bank_transaction.amount,
            content=bank_transaction.content,
            posted_at=bank_transaction.posted_at,
            raw_json=bank_transaction.raw,
            state="new",
        )
        session.add(transaction)
        await session.flush()

        paid_event: dict[str, Any] | None = None
        enqueued_webhook = False
        if bank_transaction.amount > 0:
            paid_event, enqueued_webhook = await _try_match_transaction(
                session, transaction
            )

        await session.commit()
    await session.refresh(transaction)

    # Sau commit: bắn pub/sub best-effort. Không chặn flow nếu Redis lỗi.
    if paid_event is not None or enqueued_webhook:
        await _publish_post_commit(paid_event=paid_event, kick_webhook=enqueued_webhook)

    return transaction


async def _publish_post_commit(
    *, paid_event: dict[str, Any] | None, kick_webhook: bool
) -> None:
    """Publish Redis events sau khi commit DB.

    Tách hàm riêng để mock trong test + cô lập import (lười load redis).
    """
    try:
        from packages.infra_pubsub import publish, publish_json

        if paid_event is not None:
            order_id = paid_event.get("order_id")
            if order_id:
                await publish_json(f"topup:paid:{order_id}", paid_event)
        if kick_webhook:
            await publish("webhook:kick", "1")
    except Exception:  # noqa: BLE001
        logger.warning("publish_post_commit_failed", exc_info=True)


async def _record_system_audit(
    session: AsyncSession,
    *,
    action: str,
    target_type: str,
    target_id: str,
    after: dict[str, Any] | None = None,
) -> None:
    """Best-effort audit cho action do worker/system tự sinh.

    Phân biệt với audit user qua actor='system'. Lỗi ghi audit không được
    chặn flow ingest.
    """
    try:
        from packages.security.audit import record_audit

        await record_audit(
            session,
            actor="system",
            action=action,
            target_type=target_type,
            target_id=target_id,
            after=after,
        )
    except Exception:  # noqa: BLE001
        logger.exception("system_audit_failed", extra={"action": action})


async def _try_match_transaction(
    session: AsyncSession, transaction: Transaction
) -> tuple[dict[str, Any] | None, bool]:
    """Thử match transaction với pending order.

    Trả ``(paid_event, enqueued_webhook)``:
    - ``paid_event``: payload publish lên ``topup:paid:{order_id}`` nếu match.
    - ``enqueued_webhook``: True nếu có insert >=1 WebhookAttempt.
    """
    candidates = (
        await session.scalars(
            select(Order)
            .where(Order.status == "pending")
            .where(Order.bank_account_id == transaction.bank_account_id)
            .where(Order.amount_vnd == transaction.amount_vnd)
        )
    ).all()

    match = find_order_match(
        MatchInput(amount=transaction.amount_vnd, content=transaction.content),
        [
            MatchCandidate(
                id=order.id,
                code=order.code,
                amount=order.amount_vnd,
                status=cast(OrderStatus, order.status),
                expired_at=order.expired_at,
            )
            for order in candidates
        ],
    )
    metrics.match_total.labels(result=match.status).inc()

    paid_event: dict[str, Any] | None = None
    enqueued_webhook = False

    if match.status == "matched" and match.order_id is not None:
        order = next(order for order in candidates if order.id == match.order_id)
        order.status = transition_order(order.status, "paid")
        order.paid_tx_id = transaction.id
        order.paid_at = utcnow()
        order.updated_at = utcnow()
        transaction.matched_order_id = order.id
        transaction.state = "matched"
        await _record_system_audit(
            session,
            action="system.match_paid",
            target_type="order",
            target_id=order.id,
            after={
                "status": "paid",
                "amount_vnd": int(order.amount_vnd),
                "transaction_id": transaction.id,
                "bank_ref_no": transaction.bank_ref_no,
            },
        )
        # Topup: credit ví user (idempotent qua wallet idempotency_key).
        # Notification chỉ ghi outbox (Notification table); SMTP/Telegram
        # gửi async ở scheduler — không block lock User trong ingest.
        try:
            from packages.billing.topup import credit_wallet_for_topup, is_topup_order

            if is_topup_order(order):
                await credit_wallet_for_topup(session, order)
                await _notify_topup_credited(
                    session, order=order, transaction=transaction
                )
        except Exception:  # noqa: BLE001
            # Không chặn flow ingest; lỗi credit sẽ retry ở batch reconcile.
            logger.exception("topup_credit_failed", extra={"order": order.id})

        webhook_count = await _enqueue_webhook(
            session, order=order, transaction=transaction
        )
        enqueued_webhook = webhook_count > 0
        metrics.orders_total.labels(status="paid").inc()

        paid_event = {
            "order_id": order.id,
            "code": order.code,
            "amount_vnd": int(order.amount_vnd),
            "bank_ref_no": transaction.bank_ref_no,
        }
    elif match.status == "ambiguous":
        transaction.state = "review"
        await _record_system_audit(
            session,
            action="system.match_ambiguous",
            target_type="transaction",
            target_id=transaction.id,
            after={
                "amount_vnd": int(transaction.amount_vnd),
                "bank_ref_no": transaction.bank_ref_no,
            },
        )
    else:
        transaction.state = "unmatched"

    return paid_event, enqueued_webhook


async def _notify_topup_credited(
    session: AsyncSession,
    *,
    order: Order,
    transaction: Transaction,
) -> None:
    """Best-effort ghi outbox notify ``topup_credited``.

    Chỉ INSERT vào bảng `Notification`. Không gọi SMTP/Telegram đồng bộ —
    scheduler ``notification_dispatch_job`` sẽ pickup async.
    """
    try:
        from packages.db.models import User
        from packages.notifications.dispatcher import notify

        meta = order.metadata_json or {}
        user_id = meta.get("user_id")
        if not user_id:
            return
        user = await session.get(User, user_id)
        if user is None:
            return
        await notify(
            session,
            user=user,
            kind="topup_credited",
            title="Nạp ví thành công",
            body=(
                f"Đơn {order.code} đã được ghi nhận: "
                f"+{int(order.amount_vnd):,} VND."
            ),
            payload={
                "order_id": order.id,
                "code": order.code,
                "amount_vnd": int(order.amount_vnd),
                "bank_ref_no": transaction.bank_ref_no,
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "notify_topup_credited_failed", extra={"order": order.id}
        )


async def _enqueue_webhook(
    session: AsyncSession, *, order: Order, transaction: Transaction
) -> int:
    """Insert 1 WebhookAttempt cho mỗi webhook active. Trả số lượng đã enqueue."""
    webhooks = list(
        (await session.scalars(select(Webhook).where(Webhook.active.is_(True)))).all()
    )
    for webhook in webhooks:
        attempt = WebhookAttempt.new(
            webhook_id=webhook.id,
            order_id=order.id,
            transaction_id=transaction.id,
            payload=_build_payload(order, transaction),
        )
        session.add(attempt)
    return len(webhooks)


def _build_payload(order: Order, transaction: Transaction) -> dict[str, Any]:
    # Payload có cả flat keys (`order_id`, `code`, `amount_vnd`, `customer_ref`,
    # `metadata`, `bank_ref_no`) lẫn nested keys (`order.*`, `transaction.*`) để
    # client cũ và mới đều parse được. Docs ưu tiên các flat key vì dễ đọc.
    posted_at_iso: str | None = None
    if isinstance(transaction.posted_at, datetime):
        posted_at_iso = transaction.posted_at.isoformat()
    elif transaction.posted_at:
        posted_at_iso = str(transaction.posted_at)

    return {
        "id": f"evt_{transaction.id}",
        "type": "payment.succeeded",
        "created_at": utcnow().isoformat(),
        "data": {
            # Flat keys — preferred shape for integrators (matches docs).
            "order_id": order.id,
            "transaction_id": transaction.id,
            "code": order.code,
            "amount_vnd": int(order.amount_vnd),
            "bank_ref_no": transaction.bank_ref_no,
            "posted_at": posted_at_iso,
            "customer_ref": order.customer_ref,
            "metadata": order.metadata_json or {},
            # Nested aliases — kept for backwards compatibility with v0 clients
            # that read `data.order.code` / `data.transaction.ref`.
            "order": {
                "id": order.id,
                "code": order.code,
                "amount": int(order.amount_vnd),
                "amount_vnd": int(order.amount_vnd),
                "status": order.status,
            },
            "transaction": {
                "id": transaction.id,
                "ref": transaction.bank_ref_no,
                "bank_ref_no": transaction.bank_ref_no,
                "amount": int(transaction.amount_vnd),
                "amount_vnd": int(transaction.amount_vnd),
                "posted_at": posted_at_iso,
                "content": transaction.content,
            },
        },
    }


__all__ = ["ingest_transaction"]
_ = sqlite_insert  # keep import for future upserts
