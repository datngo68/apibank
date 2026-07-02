from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import CryptoCallback, CryptoInvoice, utcnow
from packages.webhook import decrypt_webhook_secret

RETRY_DELAYS = [60, 300, 900, 3600, 21600, 86400]


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sign_payload(secret: str, timestamp: str, raw_body: str) -> str:
    message = f"{timestamp}.{raw_body}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify_signature(secret: str, timestamp: str, raw_body: str, signature: str) -> bool:
    expected = sign_payload(secret, timestamp, raw_body)
    return hmac.compare_digest(expected, signature)


def build_invoice_event(invoice: CryptoInvoice, event_type: str) -> dict[str, Any]:
    return {
        "event": event_type,
        "trans_id": invoice.trans_id,
        "request_id": invoice.request_id,
        "merchant_id": invoice.merchant_id,
        "amount": str(invoice.requested_amount),
        "pay_amount": str(invoice.pay_amount),
        "received": str(invoice.received_amount),
        "token": invoice.metadata_json.get("token"),
        "network": invoice.metadata_json.get("network"),
        "address": invoice.address,
        "status": invoice.status,
        "from_address": invoice.from_address,
        "transaction_id": invoice.transaction_id,
        "confirmations": invoice.confirmations,
        "paid_at": invoice.paid_at.isoformat() if invoice.paid_at else None,
        "timestamp": utcnow().isoformat(),
    }


async def enqueue_invoice_callback(
    session: AsyncSession,
    *,
    invoice: CryptoInvoice,
    event_type: str,
) -> CryptoCallback | None:
    if not invoice.callback_url:
        return None
    payload = build_invoice_event(invoice, event_type)
    timestamp = payload["timestamp"]
    raw_body = canonical_json(payload)
    secret = (
        decrypt_webhook_secret(invoice.webhook_secret_enc) if invoice.webhook_secret_enc else ""
    )
    signature = sign_payload(secret, timestamp, raw_body) if secret else None
    callback = CryptoCallback(
        invoice_id=invoice.id,
        event_type=event_type,
        payload_json=payload,
        signature=signature,
        state="pending",
        next_retry_at=utcnow(),
    )
    session.add(callback)
    await session.flush()
    return callback


async def dispatch_due_callbacks(session: AsyncSession, *, limit: int = 100) -> int:
    callbacks = list(
        (
            await session.scalars(
                select(CryptoCallback)
                .where(CryptoCallback.state.in_(["pending", "failed"]))
                .where(CryptoCallback.next_retry_at <= utcnow())
                .order_by(CryptoCallback.next_retry_at.asc())
                .limit(limit)
            )
        ).all()
    )
    sent = 0
    async with httpx.AsyncClient(timeout=10) as client:
        for callback in callbacks:
            invoice = await session.get(CryptoInvoice, callback.invoice_id)
            if invoice is None or not invoice.callback_url:
                callback.state = "dead_letter"
                callback.last_error = "invoice or callback_url missing"
                continue
            raw_body = canonical_json(callback.payload_json)
            timestamp = str(callback.payload_json.get("timestamp") or utcnow().isoformat())
            headers = {"Content-Type": "application/json", "X-APIBank-Timestamp": timestamp}
            if callback.signature:
                headers["X-APIBank-Signature"] = callback.signature
            try:
                resp = await client.post(invoice.callback_url, content=raw_body, headers=headers)
                callback.attempt_count += 1
                callback.last_status_code = resp.status_code
                if 200 <= resp.status_code < 300:
                    callback.state = "sent"
                    callback.sent_at = utcnow()
                    sent += 1
                else:
                    callback.state = "failed"
                    callback.last_error = resp.text[:1000]
            except Exception as exc:  # noqa: BLE001
                callback.attempt_count += 1
                callback.state = "failed"
                callback.last_error = str(exc)[:1000]
            if callback.state == "failed":
                if callback.attempt_count >= callback.max_attempts:
                    callback.state = "dead_letter"
                else:
                    delay = RETRY_DELAYS[min(callback.attempt_count - 1, len(RETRY_DELAYS) - 1)]
                    callback.next_retry_at = utcnow() + timedelta(seconds=delay)
    await session.flush()
    return sent
