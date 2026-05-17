"""Telegram bot integration — đọc token từ AppConfig, fallback `.env`.

API:
    await send_telegram(text)                       # gửi tới admin_chat_id mặc định
    await send_telegram(text, chat_id=...)          # chỉ định chat
    await send_telegram(text, reply_markup=...)     # inline keyboard

    await set_webhook(token, url, secret_token)
    await delete_webhook(token)
    await get_me(token) → {username, ...}
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


async def _resolve_telegram(session: AsyncSession | None) -> dict[str, Any]:
    runtime_cfg: dict[str, Any] = {}
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
    chat_id = runtime_cfg.get("admin_chat_id") or ""
    enabled = bool(runtime_cfg.get("enabled"))
    secret = runtime_cfg.get("webhook_secret") or ""

    if not token or not enabled:
        settings = get_settings()
        token = token or settings.telegram_bot_token
        chat_id = chat_id or settings.telegram_chat_id
        enabled = enabled or bool(settings.telegram_bot_token)

    return {
        "token": token,
        "admin_chat_id": chat_id,
        "enabled": enabled,
        "webhook_secret": secret,
    }


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
