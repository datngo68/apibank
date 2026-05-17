"""Telegram webhook handler.

Bot nhận update qua POST /api/v1/telegram/webhook. Hỗ trợ:
- Lệnh `/start <token>` để link admin chat (token sinh từ admin console).
- Inline callback button confirm/cancel order trong chat admin.

Verify bằng header `X-Telegram-Bot-Api-Secret-Token` nếu setWebhook đã đặt secret.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.config import runtime as config_runtime
from packages.db.models import EmailToken, Order
from packages.db.session import get_session
from packages.notifications import telegram as tg

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/telegram", tags=["telegram"], include_in_schema=False)

KIND_TG_LINK = "tg_link"
KIND_USER_TG_LINK = "user_tg_link"


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, Any]:
    cfg = await config_runtime.get_decrypted(
        session, tg.TELEGRAM_KEY, tg.TELEGRAM_ENCRYPTED_FIELDS
    )
    expected_secret = cfg.get("webhook_secret") or ""
    if expected_secret and x_telegram_bot_api_secret_token != expected_secret:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="invalid secret"
        )

    update = await request.json()
    token = cfg.get("bot_token") or ""
    if not token:
        return {"ok": False, "reason": "telegram_disabled"}

    # 1. Message text
    message = update.get("message")
    if message:
        await _handle_message(session, message, token=token)

    # 2. Callback query (inline button)
    callback = update.get("callback_query")
    if callback:
        await _handle_callback(
            session,
            callback,
            token=token,
            admin_chat_id=cfg.get("admin_chat_id"),
        )

    await session.commit()
    return {"ok": True}


async def _handle_message(
    session: AsyncSession, message: dict[str, Any], *, token: str
) -> None:
    text = (message.get("text") or "").strip()
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if not chat_id or not text:
        return

    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        if len(parts) == 2:
            link_token = parts[1].strip()
            # Thử admin link trước
            if await _consume_link_token(session, link_token, chat_id=str(chat_id)):
                await tg.send_telegram(
                    "✅ *Đã liên kết admin chat thành công.*\nTôi sẽ gửi thông báo về đây.",
                    chat_id=chat_id,
                    session=session,
                )
                return
            # Thử user link
            user = await _consume_user_link_token(
                session, link_token, chat_id=str(chat_id)
            )
            if user is not None:
                await tg.send_telegram(
                    f"✅ *Xin chào {user.full_name or user.email}!*\n"
                    "Đã liên kết tài khoản APIBank với Telegram của bạn.\n"
                    "Bạn sẽ nhận thông báo topup, hết hạn gói, webhook lỗi qua chat này.",
                    chat_id=chat_id,
                    session=session,
                )
                return
        await tg.send_telegram(
            "Chào bạn! Đây là bot APIBank. Mở app web → Cài đặt → Liên kết Telegram "
            "để nhận thông báo.",
            chat_id=chat_id,
            session=session,
        )
        return

    # Lệnh khác (chỉ admin chat)
    runtime_cfg = await config_runtime.get_decrypted(
        session, tg.TELEGRAM_KEY, tg.TELEGRAM_ENCRYPTED_FIELDS
    )
    if str(chat_id) != str(runtime_cfg.get("admin_chat_id") or ""):
        return

    if text in ("/help", "/menu"):
        await tg.send_telegram(
            "*APIBank bot*\n"
            "- /status — xem số đơn pending\n"
            "- Khi có topup mới, mình sẽ gửi nút Confirm/Cancel ngay tại chat này.",
            chat_id=chat_id,
            session=session,
        )


async def _consume_link_token(
    session: AsyncSession, raw_token: str, *, chat_id: str
) -> bool:
    """Tìm EmailToken kind=tg_link, nếu hợp lệ → set admin_chat_id."""
    from packages.security.tokens import hash_token

    digest = hash_token(raw_token)
    record = (
        await session.scalars(
            select(EmailToken)
            .where(EmailToken.token_hash == digest)
            .where(EmailToken.kind == KIND_TG_LINK)
        )
    ).first()
    if record is None:
        return False
    now = datetime.now(UTC)
    expires = record.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if record.used_at is not None or expires < now:
        return False

    record.used_at = now
    cfg = await config_runtime.get_config(session, tg.TELEGRAM_KEY)
    cfg["admin_chat_id"] = str(chat_id)
    await config_runtime.set_config(
        session,
        tg.TELEGRAM_KEY,
        cfg,
        actor_id="telegram_link",
        encrypt_fields=tg.TELEGRAM_ENCRYPTED_FIELDS,
    )
    return True


async def _consume_user_link_token(
    session: AsyncSession, raw_token: str, *, chat_id: str
):
    """Tìm EmailToken kind=user_tg_link, nếu hợp lệ → set User.telegram_chat_id."""
    from packages.db.models import User
    from packages.security.tokens import hash_token

    digest = hash_token(raw_token)
    record = (
        await session.scalars(
            select(EmailToken)
            .where(EmailToken.token_hash == digest)
            .where(EmailToken.kind == KIND_USER_TG_LINK)
        )
    ).first()
    if record is None:
        return None
    now = datetime.now(UTC)
    expires = record.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if record.used_at is not None or expires < now:
        return None

    user = await session.get(User, record.user_id)
    if user is None or user.status != "active":
        return None
    record.used_at = now
    user.telegram_chat_id = str(chat_id)
    return user


async def _handle_callback(
    session: AsyncSession,
    callback: dict[str, Any],
    *,
    token: str,
    admin_chat_id: str | None,
) -> None:
    callback_id = callback.get("id")
    data = callback.get("data") or ""
    chat = (callback.get("message") or {}).get("chat") or {}
    chat_id = str(chat.get("id") or "")

    if not callback_id or not data:
        return

    if not admin_chat_id or chat_id != str(admin_chat_id):
        await tg.answer_callback_query(token, callback_id, text="Không có quyền.")
        return

    action, _, target = data.partition(":")
    if not target:
        await tg.answer_callback_query(token, callback_id, text="Dữ liệu không hợp lệ.")
        return

    order = await session.get(Order, target)
    if order is None:
        await tg.answer_callback_query(token, callback_id, text="Không tìm thấy đơn.")
        return

    if action == "confirm":
        if order.status == "pending":
            order.status = "paid"
            order.paid_at = datetime.now(UTC)
            order.updated_at = datetime.now(UTC)
        await tg.answer_callback_query(token, callback_id, text=f"✅ Đã confirm {order.code}")
    elif action == "cancel":
        if order.status == "pending":
            order.status = "canceled"
            order.updated_at = datetime.now(UTC)
        await tg.answer_callback_query(token, callback_id, text=f"❌ Đã hủy {order.code}")
    else:
        await tg.answer_callback_query(token, callback_id, text="Lệnh không hỗ trợ.")
