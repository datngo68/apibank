from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from redis.asyncio import Redis
from sqlalchemy import update

from packages.banks import poll_kick
from packages.banks.base import BankAdapter, BankAuthError, BankRateLimited
from packages.banks.registry import (
    build_adapter,
    decode_credentials,
    list_active_accounts,
    load_cursor,
    save_cursor,
)
from packages.config import runtime as config_runtime
from packages.config.settings import get_settings
from packages.core.ingest import ingest_transaction
from packages.db.models import BankAccount
from packages.db.session import get_sessionmaker
from packages.infra_lock import redis_lock
from packages.obs import metrics
from packages.obs.logging import configure_logging
from packages.obs.sentry import init_sentry
from packages.security.crypto import FernetCipher

logger = logging.getLogger(__name__)

shutdown_event = asyncio.Event()


def _install_shutdown_handlers() -> None:
    import signal

    def _on_signal(signum: int, _frame: object) -> None:
        logger.info("shutdown_signal", extra={"signum": signum})
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(ValueError, OSError):
            signal.signal(sig, _on_signal)


def _build_cipher() -> FernetCipher | None:
    keys = get_settings().fernet_keys
    if not keys:
        return None
    return FernetCipher.from_keys(keys)


async def _update_account_status(
    *,
    bank_account_id: str,
    polling_status: str,
    last_error: str | None = None,
    bump_login_at: bool = False,
    bump_poll_at: bool = False,
    audit_action: str | None = None,
) -> None:
    """Cập nhật trạng thái runtime của BankAccount để admin/CLI quan sát.

    Best-effort: lỗi DB ở đây không được làm sập poll loop.

    Khi `audit_action` được set (vd "system.bank_login_failed"), cũng ghi
    1 dòng audit_log với actor='system' để dashboard phân biệt với action
    do user.
    """
    sessionmaker = get_sessionmaker()
    values: dict[str, Any] = {
        "polling_status": polling_status,
        "last_error": last_error,
    }
    now = datetime.now(UTC)
    if bump_login_at:
        values["last_login_at"] = now
    if bump_poll_at:
        values["last_poll_at"] = now
    try:
        async with sessionmaker() as session:
            await session.execute(
                update(BankAccount).where(BankAccount.id == bank_account_id).values(**values)
            )
            if audit_action is not None:
                from packages.security.audit import record_audit

                await record_audit(
                    session,
                    actor="system",
                    action=audit_action,
                    target_type="bank_account",
                    target_id=bank_account_id,
                    after={"polling_status": polling_status, "last_error": last_error},
                )
                if audit_action == "system.bank_login_failed":
                    await _notify_bank_login_failed(
                        session,
                        bank_account_id=bank_account_id,
                        error=last_error,
                    )
            await session.commit()
    except Exception:  # noqa: BLE001
        logger.exception("update_account_status_failed", extra={"bank_account_id": bank_account_id})


async def _notify_bank_login_failed(
    session: Any,
    *,
    bank_account_id: str,
    error: str | None,
) -> None:
    """Gửi notify "bank_login_failed" cho chủ bank account.

    Throttle: chỉ gửi lần đầu khi `polling_status` chuyển thành `auth_failed`,
    không spam mỗi retry. Implement bằng cách check noti gần nhất trong 1h.
    """
    from datetime import timedelta

    from sqlalchemy import select

    from packages.db.models import Notification, User
    from packages.notifications.dispatcher import notify

    bank = await session.get(BankAccount, bank_account_id)
    if bank is None or bank.user_id is None:
        return
    user = await session.get(User, bank.user_id)
    if user is None:
        return
    now = datetime.now(UTC)
    recent = (
        await session.scalars(
            select(Notification)
            .where(Notification.user_id == user.id)
            .where(Notification.kind == "bank_login_failed")
            .where(Notification.created_at > now - timedelta(hours=1))
        )
    ).first()
    if recent is not None:
        return
    try:
        await notify(
            session,
            user=user,
            kind="bank_login_failed",
            title=f"Đăng nhập ngân hàng thất bại — {bank.bank_code}",
            body=(
                f"Tài khoản {bank.account_no} không đăng nhập được. "
                f"Lỗi: {error or 'không xác định'}. "
                "Vui lòng cập nhật mật khẩu trong phần Bank accounts."
            ),
            payload={
                "bank_account_id": bank.id,
                "bank_code": bank.bank_code,
                "error": error,
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "notify_bank_login_failed_emit_failed",
            extra={"bank_account_id": bank.id},
        )


async def _poll_account(account: BankAccount, *, redis: Redis | None) -> None:
    settings = get_settings()
    cipher = _build_cipher()
    if cipher is None:
        logger.error("fernet_keys missing, cannot decrypt credentials")
        return
    username, password = decode_credentials(account, cipher=cipher)
    adapter: BankAdapter = build_adapter(
        bank_code=account.bank_code, username=username, password=password
    )

    # Re-login với backoff thay vì exit task; nếu MB rớt session/captcha OCR
    # fail, task vẫn sống và tự thử lại — không cần restart server.
    login_backoff = 30
    while not shutdown_event.is_set():
        try:
            await adapter.login()
            logger.info("bank_login_ok", extra={"bank_account_id": account.id})
            await _update_account_status(
                bank_account_id=account.id,
                polling_status="running",
                last_error=None,
                bump_login_at=True,
            )
            break
        except BankAuthError as exc:
            logger.exception(
                "bank_login_failed_retrying",
                extra={"bank_account_id": account.id, "retry_in": login_backoff},
            )
            metrics.bank_login_failure_total.labels(bank=account.bank_code).inc()
            await _update_account_status(
                bank_account_id=account.id,
                polling_status="auth_failed",
                last_error=f"{type(exc).__name__}: {exc}",
                audit_action="system.bank_login_failed",
            )
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=login_backoff)
                return  # shutdown trong lúc đợi
            except TimeoutError:
                login_backoff = min(login_backoff * 2, 600)  # max 10 phút
                continue

    sessionmaker = get_sessionmaker()
    kick_event = poll_kick.register(account.id)
    try:
        while not shutdown_event.is_set():
            try:
                async with sessionmaker() as session:
                    cursor = await load_cursor(session, bank_account_id=account.id)
                    end = datetime.now(UTC)
                    cursor_seen = cursor.last_seen_at
                    if cursor_seen is not None and cursor_seen.tzinfo is None:
                        cursor_seen = cursor_seen.replace(tzinfo=UTC)
                    start = (
                        cursor_seen if cursor_seen is not None else end - timedelta(days=2)
                    )
                    start = max(start, end - timedelta(days=2))
                    last_ref = cursor.last_ref_no
                    async for bank_tx in adapter.list_transactions(account.account_no, start, end):
                        await ingest_transaction(
                            session, bank_account_id=account.id, bank_transaction=bank_tx
                        )
                        last_ref = bank_tx.bank_ref_no
                    await save_cursor(
                        session,
                        bank_account_id=account.id,
                        last_seen_at=end,
                        last_ref_no=last_ref,
                    )
                    await session.commit()
                    metrics.poll_success_total.labels(bank=account.bank_code).inc()
                    metrics.poller_last_success_timestamp.labels(
                        bank_account_id=account.id
                    ).set_to_current_time()
                    logger.debug(
                        "poll_tick_ok",
                        extra={
                            "bank_account_id": account.id,
                            "until": end.isoformat(),
                        },
                    )
                await _update_account_status(
                    bank_account_id=account.id,
                    polling_status="running",
                    last_error=None,
                    bump_poll_at=True,
                )
            except BankAuthError as exc:
                logger.warning("session_expired_relogin", extra={"bank_account_id": account.id})
                await _update_account_status(
                    bank_account_id=account.id,
                    polling_status="auth_failed",
                    last_error=f"{type(exc).__name__}: {exc}",
                )
                try:
                    await adapter.login()
                    await _update_account_status(
                        bank_account_id=account.id,
                        polling_status="running",
                        last_error=None,
                        bump_login_at=True,
                    )
                except BankAuthError as relogin_exc:
                    logger.exception(
                        "bank_relogin_failed",
                        extra={"bank_account_id": account.id},
                    )
                    metrics.bank_login_failure_total.labels(bank=account.bank_code).inc()
                    await _update_account_status(
                        bank_account_id=account.id,
                        polling_status="auth_failed",
                        last_error=f"{type(relogin_exc).__name__}: {relogin_exc}",
                        audit_action="system.bank_login_failed",
                    )
                    # fall through tới sleep poll_interval rồi tiếp tục thử lại
            except BankRateLimited:
                logger.warning("rate_limited", extra={"bank_account_id": account.id})
                await _update_account_status(
                    bank_account_id=account.id,
                    polling_status="rate_limited",
                    last_error="rate_limited",
                )
                await asyncio.sleep(60)
            except Exception as exc:
                metrics.poll_failure_total.labels(bank=account.bank_code).inc()
                logger.exception("poll_failed", extra={"bank_account_id": account.id})
                await _update_account_status(
                    bank_account_id=account.id,
                    polling_status="error",
                    last_error=f"{type(exc).__name__}: {exc}"[:1000],
                    audit_action="system.poll_failed",
                )
                await asyncio.sleep(30)
            else:
                # Đợi tới poll_interval HOẶC khi kick (nút "Tôi đã chuyển khoản"
                # / API publish bank:poll:kick) để wake sớm.
                kick_event.clear()
                try:
                    await asyncio.wait_for(
                        kick_event.wait(), timeout=settings.poll_interval
                    )
                    logger.info(
                        "poll_kicked_early", extra={"bank_account_id": account.id}
                    )
                except TimeoutError:
                    pass
            if redis is not None:
                # heartbeat: refresh lock (best-effort)
                with contextlib.suppress(Exception):
                    await redis.set(f"poller:lock:{account.id}", "1", ex=120, xx=True)
    finally:
        poll_kick.unregister(account.id)


async def _supervised(account: BankAccount, *, redis: Redis | None) -> None:
    lock_key = f"poller:lock:{account.id}"
    if redis is None:
        await _poll_account(account, redis=None)
        return
    async with redis_lock(redis, lock_key, ttl_seconds=120) as acquired:
        if not acquired:
            logger.info("lock_busy", extra={"bank_account_id": account.id})
            return
        await _poll_account(account, redis=redis)


async def _account_kick_listener(stop: asyncio.Event) -> None:
    """Subscribe channel ``bank:account:added`` để wake up rescan ngay.

    Route POST /me/bank-accounts publish channel này sau commit. Worker
    nhận message → set event để main loop rescan + spawn task mới.
    Best-effort: nếu Redis unavailable thì sleep dài rồi exit; main loop
    vẫn rescan định kỳ qua RESCAN_INTERVAL_SEC.
    """
    from packages.infra_pubsub import subscribe, wait_for_message

    while not stop.is_set():
        try:
            async with subscribe("bank:account:added") as pubsub:
                if pubsub is None:
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=60)
                    except TimeoutError:
                        continue
                    return
                while not stop.is_set():
                    msg = await wait_for_message(pubsub, timeout=1.0)
                    if msg is not None:
                        rescan_event.set()
        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001
            logger.exception("bank_kick_listener_error")
            try:
                await asyncio.wait_for(stop.wait(), timeout=5)
            except TimeoutError:
                continue
            return


# Khoảng thời gian rescan DB tìm bank account mới (safety net khi Redis down).
RESCAN_INTERVAL_SEC = 30
rescan_event = asyncio.Event()


async def run_poller_loop(stop_event: asyncio.Event | None = None) -> None:
    """Embedded entry point — gọi từ FastAPI lifespan.

    Hỗ trợ thêm bank account runtime: rescan DB mỗi RESCAN_INTERVAL_SEC
    hoặc khi nhận pub/sub ``bank:account:added``. Bank mới → spawn task
    poll mới ngay; bank xoá/disable → cancel task tương ứng.
    """
    global shutdown_event

    settings = get_settings()
    configure_logging(settings.log_level)
    init_sentry(component="worker")
    redis: Redis | None = None
    try:
        redis = Redis.from_url(settings.redis_url)
        await cast(Awaitable[Any], redis.ping())
    except Exception as exc:  # noqa: BLE001
        # Local dev không cần Redis (chạy 1 instance, không cần lock phân tán).
        # Log 1 dòng ngắn — khỏi đè stdout với traceback dài.
        logger.warning("redis_unavailable, skipping distributed lock: %s", exc)
        redis = None

    local_stop = stop_event or shutdown_event
    shutdown_event = local_stop

    sessionmaker = get_sessionmaker()

    # account_id -> task đang poll. Re-spawn khi bank thêm; cancel khi bank xoá.
    tasks: dict[str, asyncio.Task[Any]] = {}

    async def reconcile_accounts() -> None:
        async with sessionmaker() as session:
            current = await list_active_accounts(session)
        wanted_ids = {a.id for a in current}

        # Cancel task cho bank đã bị xoá/disable.
        for stale_id in list(tasks.keys()):
            if stale_id not in wanted_ids:
                task = tasks.pop(stale_id)
                task.cancel()
                logger.info("account_removed", extra={"bank_account_id": stale_id})

        # Spawn task cho bank mới chưa có task.
        for account in current:
            existing = tasks.get(account.id)
            if existing is not None and not existing.done():
                continue
            task = asyncio.create_task(
                _supervised(account, redis=redis), name=f"poll-{account.id}"
            )
            tasks[account.id] = task
            logger.info("account_added", extra={"bank_account_id": account.id})

    # Initial scan.
    await reconcile_accounts()
    if not tasks:
        logger.warning("no_active_accounts_yet, will rescan periodically")

    logger.info("worker_started", extra={"accounts": len(tasks)})

    kick_task = asyncio.create_task(
        _account_kick_listener(local_stop), name="bank-account-kick"
    )
    poll_kick_task = asyncio.create_task(
        poll_kick.listen(local_stop), name="poll-kick-listener"
    )
    config_invalidate_task = asyncio.create_task(
        config_runtime.listen_invalidations(local_stop),
        name="config-invalidate-listener",
    )

    try:
        while not local_stop.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    rescan_event.wait(), timeout=RESCAN_INTERVAL_SEC
                )
            rescan_event.clear()
            try:
                await reconcile_accounts()
            except Exception:  # noqa: BLE001
                logger.exception("reconcile_accounts_failed")
    finally:
        kick_task.cancel()
        poll_kick_task.cancel()
        config_invalidate_task.cancel()
        for task in tasks.values():
            task.cancel()
        await asyncio.gather(
            kick_task,
            poll_kick_task,
            config_invalidate_task,
            *tasks.values(),
            return_exceptions=True,
        )
        if redis is not None:
            await redis.aclose()


async def main() -> None:
    _install_shutdown_handlers()
    await run_poller_loop(shutdown_event)


if __name__ == "__main__":
    asyncio.run(main())
