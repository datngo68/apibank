from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from packages.db.models import WebhookAttempt, utcnow
from packages.obs import metrics
from packages.webhook import decrypt_webhook_secret, is_safe_webhook_url
from packages.webhook.signing import sign_payload

logger = logging.getLogger(__name__)

RETRY_DELAYS = [0, 30, 120, 600, 3600, 21600, 86400]
DEFAULT_CONCURRENCY = 20
DEFAULT_BATCH_SIZE = 50
# Nếu attempt đang 'dispatching' lâu hơn ngưỡng này → coi như crash giữa,
# reset về 'pending' để retry.
STUCK_DISPATCH_TIMEOUT = timedelta(minutes=5)


@dataclass
class _Outcome:
    """Kết quả 1 lần POST webhook — được apply lên DB ở pha sequential."""

    delivered: bool
    status_code: int | None
    error: str | None
    fatal_reason: str | None = None  # 'unsafe_url', 'decrypt_failed', etc.


def schedule_next(attempt: int, *, now: datetime | None = None) -> datetime:
    current = now or datetime.now(UTC)
    index = min(attempt, len(RETRY_DELAYS) - 1)
    return current + timedelta(seconds=RETRY_DELAYS[index])


async def reset_stuck_dispatching(
    session: AsyncSession, *, now: datetime | None = None
) -> int:
    """Reset attempt 'dispatching' lâu quá ngưỡng về 'pending'.

    Trả số row đã reset. Nên gọi periodically từ scheduler trước khi dispatch.
    """
    current = now or datetime.now(UTC)
    threshold = current - STUCK_DISPATCH_TIMEOUT
    result = await session.execute(
        update(WebhookAttempt)
        .where(WebhookAttempt.status == "dispatching")
        .where(WebhookAttempt.claimed_at <= threshold)
        .values(status="pending", claimed_at=None)
    )
    if result.rowcount:  # type: ignore[attr-defined]
        logger.warning(
            "webhook_dispatch_reset_stuck",
            extra={"count": result.rowcount},  # type: ignore[attr-defined]
        )
        await session.commit()
    return result.rowcount or 0  # type: ignore[attr-defined]


async def _claim_attempts(
    session: AsyncSession,
    *,
    now: datetime,
    batch_size: int,
) -> list[WebhookAttempt]:
    """Atomic claim: chuyển N row từ 'pending' → 'dispatching' và trả về.

    Mỗi dispatcher tạo claim token (microsecond unique). UPDATE atomic
    + filter status='pending' đảm bảo 2 dispatcher concurrent claim
    được disjoint sets:

    - Postgres: ``UPDATE ... WHERE id IN (SELECT ... FOR UPDATE SKIP LOCKED)``.
    - SQLite: write nào executed sau sẽ thấy status đã 'dispatching' nhờ
      WAL mode/serialized writes; filter status='pending' trong UPDATE
      đảm bảo không claim trùng.

    Sau đó load full rows bằng claim_token (giống "leasing").
    """
    bind = session.bind
    dialect = bind.dialect.name if bind is not None else "sqlite"

    # Token unique cho lần claim này. Dùng id(session) + counter để đảm
    # bảo 2 dispatcher concurrent không trùng claim_token (microsecond
    # alone không đủ — Windows có thể trùng).
    import secrets as _secrets

    claim_token = now + timedelta(microseconds=_secrets.randbelow(1_000_000))

    if dialect == "postgresql":
        stmt = (
            select(WebhookAttempt.id)
            .where(WebhookAttempt.status == "pending")
            .where(WebhookAttempt.next_run_at <= now)
            .order_by(WebhookAttempt.next_run_at.asc())
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        try:
            ids = list((await session.scalars(stmt)).all())
        except OperationalError:
            ids = []
        if not ids:
            await session.commit()
            return []
        await session.execute(
            update(WebhookAttempt)
            .where(WebhookAttempt.id.in_(ids))
            .where(WebhookAttempt.status == "pending")
            .values(status="dispatching", claimed_at=claim_token)
        )
        await session.commit()
        attempts = list(
            (
                await session.scalars(
                    select(WebhookAttempt)
                    .options(selectinload(WebhookAttempt.webhook))
                    .where(WebhookAttempt.id.in_(ids))
                    .where(WebhookAttempt.claimed_at == claim_token)
                )
            ).all()
        )
        return attempts

    # SQLite + others: UPDATE atomic với subquery LIMIT.
    # SQLAlchemy's UPDATE doesn't support LIMIT directly trên mọi dialect,
    # nhưng SQLite hỗ trợ ``UPDATE ... WHERE id IN (subquery LIMIT N)``.
    subq = (
        select(WebhookAttempt.id)
        .where(WebhookAttempt.status == "pending")
        .where(WebhookAttempt.next_run_at <= now)
        .order_by(WebhookAttempt.next_run_at.asc())
        .limit(batch_size)
        .scalar_subquery()
    )
    result = await session.execute(
        update(WebhookAttempt)
        .where(WebhookAttempt.id.in_(subq))
        .where(WebhookAttempt.status == "pending")
        .values(status="dispatching", claimed_at=claim_token)
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    if not result.rowcount:  # type: ignore[attr-defined]
        return []
    # Load các row vừa claim qua claim_token. Hai dispatcher concurrent
    # sẽ có 2 token khác nhau (microsecond) → mỗi cái load đúng phần
    # mình đã claim.
    attempts = list(
        (
            await session.scalars(
                select(WebhookAttempt)
                .options(selectinload(WebhookAttempt.webhook))
                .where(WebhookAttempt.claimed_at == claim_token)
                .where(WebhookAttempt.status == "dispatching")
            )
        ).all()
    )
    # Identity-map sync: UPDATE pha 1 dùng synchronize_session=False nên
    # các instance đã tồn tại trong session có thể giữ status='pending'
    # cached trong memory. Force expire để pha 2 (gán status='pending'
    # cho retry) thực sự được flush ra DB như dirty change.
    for attempt in attempts:
        await session.refresh(attempt, attribute_names=["status", "claimed_at"])
    return attempts


async def dispatch_due_attempts(
    session: AsyncSession,
    *,
    client: httpx.AsyncClient,
    now: datetime | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> int:
    """Drain các WebhookAttempt due qua HTTP.

    Pattern: claim atomic → gửi HTTP song song (concurrency limit) → apply
    kết quả tuần tự lên session → commit 1 lần.

    Lý do tách 2 pha: SQLAlchemy AsyncSession không an toàn khi dùng
    concurrent trên cùng connection. HTTP I/O là phần dài; DB write
    nhỏ và nhanh — gom commit cuối batch là đủ.

    Crash giữa pha HTTP → các attempt giữ status 'dispatching'. Sẽ được
    ``reset_stuck_dispatching`` reset về 'pending' sau STUCK_DISPATCH_TIMEOUT.
    """
    current = now or datetime.now(UTC)

    attempts = await _claim_attempts(
        session, now=current, batch_size=batch_size
    )
    if not attempts:
        return 0

    # Pha 1: HTTP song song. Mỗi task chỉ trả _Outcome, không touch DB.
    sem = asyncio.Semaphore(concurrency)
    metrics.webhook_dispatch_concurrency.set(0)

    async def _send_attempt(attempt: WebhookAttempt) -> _Outcome:
        async with sem:
            metrics.webhook_dispatch_concurrency.inc()
            try:
                return await _post_one(attempt, client=client, now=current)
            finally:
                metrics.webhook_dispatch_concurrency.dec()

    outcomes: list[_Outcome] = await asyncio.gather(
        *[_send_attempt(a) for a in attempts],
        return_exceptions=False,
    )

    # Pha 2: apply outcome tuần tự + commit 1 lần.
    delivered = 0
    for attempt, outcome in zip(attempts, outcomes, strict=True):
        if outcome.fatal_reason:
            attempt.status = "dead"
            attempt.last_error = outcome.fatal_reason
            attempt.claimed_at = None
            metrics.webhook_attempts_total.labels(status="dead").inc()
            continue

        attempt.attempt += 1
        attempt.last_status_code = outcome.status_code
        attempt.signature = getattr(attempt, "signature", None)

        if outcome.delivered:
            attempt.status = "delivered"
            attempt.sent_at = current
            attempt.last_error = None
            attempt.claimed_at = None
            metrics.webhook_attempts_total.labels(status="delivered").inc()
            delivered += 1
            continue

        attempt.last_error = outcome.error
        if attempt.attempt >= attempt.max_attempts:
            attempt.status = "dead"
            attempt.claimed_at = None
            metrics.webhook_attempts_total.labels(status="dead").inc()
            await _notify_webhook_dead(
                session, webhook=attempt.webhook, attempt=attempt
            )
        else:
            attempt.status = "pending"
            attempt.next_run_at = schedule_next(attempt.attempt, now=current)
            attempt.claimed_at = None
            metrics.webhook_attempts_total.labels(status="failed").inc()

    await session.commit()
    return delivered


async def _post_one(
    attempt: WebhookAttempt,
    *,
    client: httpx.AsyncClient,
    now: datetime,
) -> _Outcome:
    """Pure HTTP — không touch DB. Trả _Outcome cho caller apply."""
    webhook = attempt.webhook  # eager-loaded ở _claim_attempts
    if webhook is None or not webhook.active:
        return _Outcome(
            delivered=False,
            status_code=None,
            error=None,
            fatal_reason="webhook missing or inactive",
        )

    ok_url, reason = is_safe_webhook_url(webhook.url)
    if not ok_url:
        return _Outcome(
            delivered=False,
            status_code=None,
            error=None,
            fatal_reason=f"unsafe_url: {reason}",
        )

    try:
        secret_plain = decrypt_webhook_secret(webhook.secret_enc)
    except Exception as exc:  # noqa: BLE001
        return _Outcome(
            delivered=False,
            status_code=None,
            error=None,
            fatal_reason=f"decrypt_failed: {exc!r}",
        )

    body = json.dumps(
        attempt.payload, separators=(",", ":"), ensure_ascii=False
    ).encode()
    timestamp = int(now.timestamp())
    signature = sign_payload(secret=secret_plain, body=body, timestamp=timestamp)
    # Lưu signature lên attempt (in-memory) để pha 2 commit ra DB.
    attempt.signature = signature

    try:
        with metrics.webhook_delivery_seconds.time():
            response = await client.post(
                webhook.url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Signature": signature,
                    **(webhook.headers_json or {}),
                },
                follow_redirects=False,
            )
        if 200 <= response.status_code < 300:
            return _Outcome(
                delivered=True,
                status_code=response.status_code,
                error=None,
            )
        return _Outcome(
            delivered=False,
            status_code=response.status_code,
            error=f"http_{response.status_code}",
        )
    except Exception as exc:  # noqa: BLE001
        return _Outcome(
            delivered=False,
            status_code=None,
            error=repr(exc),
        )


def build_payload_for_event(
    *, event_id: str, order_id: str, transaction_id: str, payload_extra: dict[str, Any]
) -> dict[str, Any]:
    return {
        "id": f"evt_{event_id}",
        "type": "payment.succeeded",
        "created_at": utcnow().isoformat(),
        "data": {"order_id": order_id, "transaction_id": transaction_id, **payload_extra},
    }


async def _notify_webhook_dead(
    session: AsyncSession,
    *,
    webhook: Any,
    attempt: WebhookAttempt,
) -> None:
    """Ghi outbox notify ``webhook_failing`` cho chủ webhook khi vào dead-letter."""
    if not getattr(webhook, "user_id", None):
        return
    try:
        from packages.db.models import User
        from packages.notifications.dispatcher import notify

        user = await session.get(User, webhook.user_id)
        if user is None:
            return
        await notify(
            session,
            user=user,
            kind="webhook_failing",
            title="Webhook gửi thất bại liên tục",
            body=(
                f"Endpoint {webhook.url} đã thất bại {attempt.attempt} lần. "
                "Webhook đã chuyển sang trạng thái 'dead'; "
                f"lỗi cuối: {attempt.last_error or 'không rõ'}."
            ),
            payload={
                "webhook_id": webhook.id,
                "attempt_id": attempt.id,
                "url": webhook.url,
                "last_error": attempt.last_error,
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "notify_webhook_dead_failed",
            extra={"webhook_id": webhook.id, "attempt_id": attempt.id},
        )


__all__: list[str] = [
    "dispatch_due_attempts",
    "schedule_next",
    "build_payload_for_event",
    "reset_stuck_dispatching",
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_CONCURRENCY",
]
