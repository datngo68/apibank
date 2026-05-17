"""Google OAuth helper — đọc cấu hình từ AppConfig, build URL, exchange code.

Yêu cầu admin cấu hình client_id/secret/redirect_uri từ /app/admin/config.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from packages.config import runtime as config_runtime

CONFIG_KEY = "google_oauth"
ENCRYPTED_FIELDS = ("client_secret",)
SCOPES = "openid email profile"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


async def get_oauth_config(session: AsyncSession) -> dict[str, Any]:
    """Trả `{client_id, client_secret, redirect_uri, enabled}`. Mặc định disabled."""
    cfg = await config_runtime.get_decrypted(session, CONFIG_KEY, ENCRYPTED_FIELDS)
    return {
        "client_id": cfg.get("client_id") or "",
        "client_secret": cfg.get("client_secret") or "",
        "redirect_uri": cfg.get("redirect_uri") or "",
        "enabled": bool(cfg.get("enabled")),
    }


def build_authorize_url(state: str, *, client_id: str, redirect_uri: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "online",
        "prompt": "select_account",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


async def exchange_code(
    code: str, *, client_id: str, client_secret: str, redirect_uri: str
) -> dict[str, Any]:
    """Đổi `code` → access_token → userinfo. Trả `{sub, email, name, picture}`."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        token_resp = await client.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        token_resp.raise_for_status()
        token_payload = token_resp.json()
        access_token = token_payload.get("access_token")
        if not access_token:
            raise RuntimeError("Google OAuth: missing access_token")

        info_resp = await client.get(
            USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        info_resp.raise_for_status()
        info = info_resp.json()

    return {
        "sub": info.get("sub"),
        "email": (info.get("email") or "").lower(),
        "name": info.get("name") or info.get("given_name"),
        "picture": info.get("picture"),
        "email_verified": bool(info.get("email_verified")),
    }
