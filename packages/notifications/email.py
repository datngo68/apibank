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


async def resolve_smtp(session: AsyncSession | None) -> dict[str, Any]:
    """Đọc cấu hình SMTP. Ưu tiên AppConfig (admin chỉnh từ UI), fallback `.env`.

    Trả ``{host, port, user, password, from_addr, use_tls, enabled,
    configured, password_set, source}``. ``configured = bool(host)`` —
    tách khỏi `enabled` để admin/UI biết "đã có host nhưng chưa bật" và
    "chưa cấu hình gì".
    """
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

    if runtime_cfg.get("host"):
        return {
            "host": runtime_cfg.get("host", ""),
            "port": int(runtime_cfg.get("port", 587) or 587),
            "user": runtime_cfg.get("user", "") or "",
            "password": runtime_cfg.get("password") or "",
            "from_addr": runtime_cfg.get("from_addr") or runtime_cfg.get("user", ""),
            "use_tls": bool(runtime_cfg.get("use_tls", True)),
            "enabled": bool(runtime_cfg.get("enabled")),
            "configured": True,
            "password_set": bool(runtime_cfg.get("password")),
            "source": "app_config",
        }

    settings = get_settings()
    env_host = getattr(settings, "smtp_host", "") or ""
    env_user = getattr(settings, "smtp_user", "") or ""
    env_password = getattr(settings, "smtp_password", "") or ""
    return {
        "host": env_host,
        "port": int(getattr(settings, "smtp_port", 587) or 587),
        "user": env_user,
        "password": env_password,
        "from_addr": getattr(settings, "smtp_from", "") or env_user,
        "use_tls": bool(getattr(settings, "smtp_use_tls", True)),
        # `.env` đã set host nghĩa là deploy chủ ý — bật mặc định.
        "enabled": bool(env_host),
        "configured": bool(env_host),
        "password_set": bool(env_password),
        "source": "env",
    }


async def _resolve_smtp(session: AsyncSession | None) -> dict[str, Any]:
    """Backward-compat wrapper. Mới: dùng :func:`resolve_smtp`."""
    cfg = await resolve_smtp(session)
    # Hot path send_email kiểm tra ``host`` để biết có thực sự gửi được — giữ
    # nguyên contract cũ. ``enabled=False`` từ resolver vẫn cho gửi nếu host
    # có, vì test_smtp trước đây không yêu cầu enabled.
    return cfg


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
    cfg = await resolve_smtp(session)
    if not cfg["host"] or not cfg["enabled"]:
        logger.info(
            "email_skipped_no_smtp",
            extra={
                "to": to,
                "subject": subject,
                "source": cfg["source"],
                "configured": cfg["configured"],
                "enabled": cfg["enabled"],
            },
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
    cfg = await resolve_smtp(session)
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
