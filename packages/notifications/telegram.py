"""Telegram bot integration — đọc token từ AppConfig, fallback `.env`.

API:
    cfg = await resolve_telegram(session)               # dict thống nhất
    await send_telegram(text)                           # gửi tới admin_chat_id mặc định
    await send_telegram(text, chat_id=...)              # chỉ định chat
    await send_telegram(text, reply_markup=...)         # inline keyboard

    await set_webhook(token, url, secret_token)
    await delete_webhook(token)
    await get_me(token) → {username, ...}

`resolve_telegram` là single source of truth: mọi call site (route admin,
route user, worker, scheduler) phải dùng để tránh tình trạng chỗ thì thấy
"đã configured", chỗ thì báo "chưa". Field ``configured`` = đã có token
(bất kể `enabled` toggle): user link Telegram chỉ cần token, không phụ
thuộc admin có bật notify hay không.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from packages.config import runtime as config_runtime
from packages.config.settings import get_settings
from packages.db.session import get_sessionmaker

logger = logging.getLogger(__name__)

TELEGRAM_KEY = "telegram"
TELEGRAM_ENCRYPTED_FIELDS = ("bot_token",)
API_BASE = "https://api.telegram.org/bot{token}/{method}"


async def resolve_telegram(session: AsyncSession | None = None) -> dict[str, Any]:
    """Đọc cấu hình Telegram thống nhất. Ưu tiên AppConfig (admin chỉnh từ UI),
    fallback ``.env``.

    Trả ``{token, admin_chat_id, enabled, configured, webhook_url,
    webhook_secret, bot_username, source}``:

    - ``configured = bool(token)`` — chỉ cần có token là user link được, kể
      cả khi admin chưa bật toggle "Bật notify".
    - ``enabled`` chỉ kiểm soát send_telegram (notify outbound). Route
      ``link-chat`` nên check ``configured`` thay vì ``enabled``.
    - ``source`` = ``"app_config"`` hoặc ``"env"`` để debug khi user kêu
      "đã save mà vẫn không nhận thấy".
    """
    if session is not None:
        runtime_cfg = await config_runtime.get_decrypted(
            session, TELEGRAM_KEY, TELEGRAM_ENCRYPTED_FIELDS
        )
    else:
        sm = get_sessionmaker()
        async with sm() as s:
            runtime_cfg = await config_runtime.get_decrypted(
                s, TELEGRAM_KEY, TELEGRAM_ENCRYPTED_FIELDS
            )

    token = runtime_cfg.get("bot_token") or ""
    chat_id = str(runtime_cfg.get("admin_chat_id") or "")
    webhook_url = runtime_cfg.get("webhook_url") or ""
    webhook_secret = runtime_cfg.get("webhook_secret") or ""
    bot_username = runtime_cfg.get("bot_username") or ""
    enabled = bool(runtime_cfg.get("enabled"))
    source = "app_config" if token else "env"

    if not token:
        settings = get_settings()
        env_token = settings.telegram_bot_token or ""
        env_chat = settings.telegram_chat_id or ""
        if env_token:
            token = env_token
            chat_id = chat_id or env_chat
            # `.env` configured nghĩa là deploy đã chủ ý bật → enabled mặc
            # định True trừ khi admin tắt rõ ràng trong AppConfig.
            if "enabled" not in runtime_cfg:
                enabled = True
            source = "env"

    return {
        "token": token,
        "admin_chat_id": chat_id,
        "enabled": enabled,
        "configured": bool(token),
        "webhook_url": webhook_url,
        "webhook_secret": webhook_secret,
        "bot_username": bot_username,
        "source": source,
    }


async def _resolve_telegram(session: AsyncSession | None) -> dict[str, Any]:
    """Backward-compat wrapper. Mới: dùng :func:`resolve_telegram`."""
    return await resolve_telegram(session)


async def send_telegram(
    text: str,
    *,
    chat_id: str | int | None = None,
    reply_markup: dict[str, Any] | None = None,
    parse_mode: str = "Markdown",
    session: AsyncSession | None = None,
) -> bool:
    cfg = await _resolve_telegram(session)
    if not cfg["enabled"] or not cfg["token"]:
        return False
    target = chat_id if chat_id is not None else cfg["admin_chat_id"]
    if not target:
        return False
    payload: dict[str, Any] = {
        "chat_id": target,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                API_BASE.format(token=cfg["token"], method="sendMessage"),
                json=payload,
            )
        response.raise_for_status()
        return True
    except Exception:  # noqa: BLE001
        logger.exception("telegram_send_failed")
        return False


async def set_webhook(
    token: str, url: str, *, secret_token: str | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {"url": url, "drop_pending_updates": True}
    if secret_token:
        payload["secret_token"] = secret_token
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            API_BASE.format(token=token, method="setWebhook"), json=payload
        )
    ctype = response.headers.get("content-type", "")
    if ctype.startswith("application/json"):
        return dict(response.json())
    return {"ok": False, "description": response.text}


async def delete_webhook(token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            API_BASE.format(token=token, method="deleteWebhook"),
            json={"drop_pending_updates": True},
        )
    ctype = response.headers.get("content-type", "")
    if ctype.startswith("application/json"):
        return dict(response.json())
    return {"ok": False, "description": response.text}


async def get_me(token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(API_BASE.format(token=token, method="getMe"))
    ctype = response.headers.get("content-type", "")
    if ctype.startswith("application/json"):
        return dict(response.json())
    return {"ok": False, "description": response.text}


async def answer_callback_query(
    token: str, callback_query_id: str, *, text: str | None = None
) -> bool:
    payload: dict[str, Any] = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                API_BASE.format(token=token, method="answerCallbackQuery"),
                json=payload,
            )
        return True
    except Exception:  # noqa: BLE001
        return False
