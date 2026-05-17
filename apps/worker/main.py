from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from redis.asyncio import Redis
from sqlalchemy import update

from packages.banks.base import BankAdapter, BankAuthError, BankRateLimited
from packages.banks.registry import (
    build_adapter,
    decode_credentials,
    list_active_accounts,
    load_cursor,
    save_cursor,
)
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
                logger.debug(
                    "poll_tick_ok", extra={"bank_account_id": account.id, "until": end.isoformat()}
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
            await asyncio.sleep(settings.poll_interval)
        if redis is not None:
            # heartbeat: refresh lock (best-effort)
            with contextlib.suppress(Exception):
                await redis.set(f"poller:lock:{account.id}", "1", ex=120, xx=True)


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


async def run_poller_loop(stop_event: asyncio.Event | None = None) -> None:
    """Embedded entry point — gọi từ FastAPI lifespan."""
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

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        accounts = await list_active_accounts(session)

    if not accounts:
        logger.warning("no_active_accounts")
        await local_stop.wait()
        return

    # Bind global shutdown event để _poll_account đọc đúng
    shutdown_event = local_stop

    tasks = [asyncio.create_task(_supervised(account, redis=redis)) for account in accounts]
    logger.info("worker_started", extra={"accounts": len(tasks)})
    try:
        await local_stop.wait()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if redis is not None:
            await redis.aclose()


async def main() -> None:
    _install_shutdown_handlers()
    await run_poller_loop(shutdown_event)


if __name__ == "__main__":
    asyncio.run(main())
