"""Email channel — gửi qua SMTP. Đọc cấu hình từ AppConfig (runtime), fallback `.env`.

Cách dùng:
    await send_email(to=..., subject=..., body=...)               # tự load AsyncSession nội bộ
    await send_email(..., session=session)                         # dùng session sẵn có
    ok, err = await send_email_test(to=..., session=session)       # cho admin "Gửi test"

Trong dev/test (không có SMTP host) → no-op, log info.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from packages.config import runtime as config_runtime
from packages.config.settings import get_settings
from packages.db.session import get_sessionmaker

logger = logging.getLogger(__name__)

SMTP_KEY = "smtp"
SMTP_ENCRYPTED_FIELDS = ("password",)


async def _resolve_smtp(session: AsyncSession | None) -> dict[str, Any]:
    """Đọc cấu hình SMTP. Ưu tiên AppConfig (admin chỉnh từ UI), fallback `.env`."""
    runtime_cfg: dict[str, Any] = {}
    if session is not None:
        runtime_cfg = await config_runtime.get_decrypted(
            session, SMTP_KEY, SMTP_ENCRYPTED_FIELDS
        )
    else:
        sm = get_sessionmaker()
        async with sm() as s:
            runtime_cfg = await config_runtime.get_decrypted(
                s, SMTP_KEY, SMTP_ENCRYPTED_FIELDS
            )

    if runtime_cfg.get("enabled") and runtime_cfg.get("host"):
        return {
            "host": runtime_cfg.get("host", ""),
            "port": int(runtime_cfg.get("port", 587) or 587),
            "user": runtime_cfg.get("user", "") or "",
            "password": runtime_cfg.get("password") or "",
            "from_addr": runtime_cfg.get("from_addr") or runtime_cfg.get("user", ""),
            "use_tls": bool(runtime_cfg.get("use_tls", True)),
            "source": "app_config",
        }

    settings = get_settings()
    return {
        "host": getattr(settings, "smtp_host", "") or "",
        "port": int(getattr(settings, "smtp_port", 587) or 587),
        "user": getattr(settings, "smtp_user", "") or "",
        "password": getattr(settings, "smtp_password", "") or "",
        "from_addr": getattr(settings, "smtp_from", "") or getattr(settings, "smtp_user", ""),
        "use_tls": bool(getattr(settings, "smtp_use_tls", True)),
        "source": "env",
    }


def _send_sync(cfg: dict[str, Any], msg: EmailMessage) -> tuple[bool, str | None]:
    if not cfg["host"]:
        return False, "smtp_not_configured"
    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=10) as smtp:
            if cfg["use_tls"]:
                smtp.starttls()
            if cfg["user"]:
                smtp.login(cfg["user"], cfg["password"])
            smtp.send_message(msg)
        return True, None
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


async def send_email(
    *,
    to: str,
    subject: str,
    body: str,
    html: str | None = None,
    session: AsyncSession | None = None,
) -> bool:
    cfg = await _resolve_smtp(session)
    if not cfg["host"]:
        logger.info(
            "email_skipped_no_smtp",
            extra={"to": to, "subject": subject, "source": cfg["source"]},
        )
        return False

    from_addr = cfg["from_addr"] or cfg["user"]
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")

    ok, err = await asyncio.to_thread(_send_sync, cfg, msg)
    if not ok:
        logger.error("email_send_failed", extra={"to": to, "error": err})
    return ok


async def send_email_test(
    *, to: str, session: AsyncSession
) -> tuple[bool, str | None]:
    """Gửi 1 email test cho admin, trả `(ok, error_message)`."""
    cfg = await _resolve_smtp(session)
    if not cfg["host"]:
        return False, "SMTP chưa được cấu hình (thiếu host)."

    msg = EmailMessage()
    msg["Subject"] = "APIBank · SMTP test"
    msg["From"] = cfg["from_addr"] or cfg["user"]
    msg["To"] = to
    msg.set_content(
        "Đây là email kiểm tra cấu hình SMTP từ APIBank admin console.\n"
        "Nếu bạn nhận được, mọi thứ đã hoạt động."
    )
    return await asyncio.to_thread(_send_sync, cfg, msg)
