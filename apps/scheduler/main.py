from __future__ import annotations

import asyncio
import contextlib
import logging

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from packages.core.reconcile_runner import reconcile
from packages.db.session import get_sessionmaker
from packages.obs import metrics
from packages.obs.logging import configure_logging
from packages.obs.sentry import init_sentry
from packages.webhook.dispatcher import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_CONCURRENCY,
    dispatch_due_attempts,
    reset_stuck_dispatching,
)

logger = logging.getLogger(__name__)

# Persistent httpx client — keep-alive cross-tick để giảm TLS handshake
# với endpoint webhook lặp lại. Khởi tạo trong start_scheduler, đóng cuối lifecycle.
_webhook_client: httpx.AsyncClient | None = None
# Lock chống chạy 2 batch dispatch đồng thời (kick + APScheduler tick).
# Chỉ tránh contention nội bộ; safety chống double-deliver vẫn dựa
# vào atomic claim trong dispatcher.
_dispatch_lock = asyncio.Lock()


def _get_webhook_client() -> httpx.AsyncClient:
    global _webhook_client
    if _webhook_client is None:
        _webhook_client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0),
            limits=httpx.Limits(
                max_connections=100,
                max_keepalive_connections=20,
                keepalive_expiry=30.0,
            ),
            follow_redirects=False,
        )
    return _webhook_client


async def reconcile_job() -> None:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        report = await reconcile(session)
        logger.info(
            "reconcile_done",
            extra={
                "imported": report.imported_transactions,
                "matched": report.matched_orders,
                "review": report.review_transactions,
            },
        )


async def webhook_job() -> None:
    """Drain WebhookAttempt due. Re-entrant safe nhờ ``_dispatch_lock``."""
    if _dispatch_lock.locked():
        # Đã có batch khác đang chạy — bỏ qua tick này, atomic claim
        # đảm bảo không miss row.
        return
    async with _dispatch_lock:
        await _run_dispatch_batch()


async def _run_dispatch_batch(*, source: str = "tick") -> int:
    sessionmaker = get_sessionmaker()
    client = _get_webhook_client()
    delivered_total = 0
    metrics.webhook_kick_total.labels(source=source).inc()
    # Loop cho tới khi rỗng hoặc đạt giới hạn an toàn — tránh 1 webhook
    # backlog lớn ngốn hết 1 tick mà vẫn chưa drain.
    for _ in range(20):
        async with sessionmaker() as session:
            await reset_stuck_dispatching(session)
            delivered = await dispatch_due_attempts(
                session,
                client=client,
                batch_size=DEFAULT_BATCH_SIZE,
                concurrency=DEFAULT_CONCURRENCY,
            )
        delivered_total += delivered
        if delivered == 0:
            break
    if delivered_total:
        logger.info(
            "webhook_dispatched",
            extra={"delivered": delivered_total, "source": source},
        )
    return delivered_total


async def notification_dispatch_job() -> None:
    """Pickup Notification rows có ``sent_at IS NULL`` rồi gửi email/Telegram."""
    from packages.notifications.dispatcher import dispatch_pending_notifications

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        sent = await dispatch_pending_notifications(session)
        if sent:
            logger.info("notification_dispatched", extra={"sent": sent})


async def expire_subscriptions_job() -> None:
    from packages.billing.subscription import expire_due_subscriptions

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        n = await expire_due_subscriptions(session)
        if n:
            await session.commit()
            logger.info("subscriptions_expired", extra={"count": n})


async def subscription_expiring_soon_job() -> None:
    """Gửi notify "subscription_expiring" cho mọi user có sub hết hạn trong 3 ngày tới.

    Idempotent qua bảng Notification: chỉ gửi nếu chưa có noti `subscription_expiring`
    cho subscription đó trong 3 ngày qua.
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from packages.db.models import Notification, Subscription, User
    from packages.notifications.dispatcher import notify

    sessionmaker = get_sessionmaker()
    now = datetime.now(UTC)
    soon = now + timedelta(days=3)
    async with sessionmaker() as session:
        rows = list(
            (
                await session.scalars(
                    select(Subscription)
                    .where(Subscription.status == "active")
                    .where(Subscription.expires_at <= soon)
                    .where(Subscription.expires_at > now)
                )
            ).all()
        )
        for sub in rows:
            recent = (
                await session.scalars(
                    select(Notification)
                    .where(Notification.user_id == sub.user_id)
                    .where(Notification.kind == "subscription_expiring")
                    .where(Notification.created_at > now - timedelta(days=3))
                )
            ).first()
            if recent is not None:
                continue
            user = await session.get(User, sub.user_id)
            if user is None:
                continue
            try:
                await notify(
                    session,
                    user=user,
                    kind="subscription_expiring",
                    title="Gói dịch vụ sắp hết hạn",
                    body=(
                        f"Gói của bạn sẽ hết hạn vào "
                        f"{sub.expires_at.isoformat(timespec='minutes')}. "
                        "Hãy gia hạn để tránh gián đoạn."
                    ),
                    payload={
                        "subscription_id": sub.id,
                        "expires_at": sub.expires_at.isoformat(),
                    },
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "notify_subscription_expiring_failed", extra={"sub": sub.id}
                )
        await session.commit()


async def _webhook_kick_listener(stop: asyncio.Event) -> None:
    """Subscribe channel ``webhook:kick`` và chạy dispatch ngay.

    Debounced: gom các kick trong 200ms thành 1 batch để không spam
    dispatch khi burst nhiều ingest.
    """
    from packages.infra_pubsub import subscribe, wait_for_message

    while not stop.is_set():
        try:
            async with subscribe("webhook:kick") as pubsub:
                if pubsub is None:
                    # Redis không sẵn — sleep dài rồi retry; APScheduler
                    # vẫn có safety net 30s.
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=60)
                    except TimeoutError:
                        continue
                    return
                while not stop.is_set():
                    msg = await wait_for_message(pubsub, timeout=1.0)
                    if msg is None:
                        continue
                    # Debounce 200ms để batch nhiều kick liền nhau.
                    await asyncio.sleep(0.2)
                    # Drain các message còn lại đã accumulate.
                    while True:
                        more = await wait_for_message(pubsub, timeout=0.0)
                        if more is None:
                            break
                    if _dispatch_lock.locked():
                        continue
                    async with _dispatch_lock:
                        try:
                            await _run_dispatch_batch(source="kick")
                        except Exception:  # noqa: BLE001
                            logger.exception("webhook_kick_dispatch_failed")
        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001
            logger.exception("webhook_kick_listener_error")
            try:
                await asyncio.wait_for(stop.wait(), timeout=5)
            except TimeoutError:
                continue
            return


async def start_scheduler(stop_event: asyncio.Event | None = None) -> None:
    """Embedded entry — gọi từ FastAPI lifespan."""
    configure_logging("INFO")
    init_sentry(component="scheduler")
    local_stop = stop_event or asyncio.Event()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(reconcile_job, "interval", minutes=5, id="reconcile")
    # Tăng từ 10s → 30s vì Redis kick xử lý near-realtime; tick còn lại
    # đóng vai trò safety-net khi Redis unavailable hoặc miss message.
    scheduler.add_job(webhook_job, "interval", seconds=30, id="webhook")
    scheduler.add_job(
        notification_dispatch_job,
        "interval",
        seconds=5,
        id="notification-dispatch",
    )
    scheduler.add_job(expire_subscriptions_job, "interval", hours=1, id="expire-subs")
    scheduler.add_job(
        subscription_expiring_soon_job,
        "interval",
        hours=12,
        id="expire-soon",
    )
    scheduler.start()
    logger.info("scheduler_started")

    kick_task = asyncio.create_task(
        _webhook_kick_listener(local_stop), name="webhook-kick-listener"
    )
    try:
        await local_stop.wait()
    finally:
        kick_task.cancel()
        with contextlib.suppress(BaseException):
            await kick_task
        scheduler.shutdown(wait=False)
        global _webhook_client
        if _webhook_client is not None:
            with contextlib.suppress(Exception):
                await _webhook_client.aclose()
            _webhook_client = None


async def main() -> None:
    shutdown = asyncio.Event()
    import signal

    def _on_signal(signum: int, _frame: object) -> None:
        logger.info("shutdown_signal", extra={"signum": signum})
        shutdown.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(ValueError, OSError):
            signal.signal(sig, _on_signal)

    await start_scheduler(shutdown)


if __name__ == "__main__":
    asyncio.run(main())
