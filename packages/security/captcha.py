"""CAPTCHA verifier (Cloudflare Turnstile / hCaptcha).

Chỉ enforce khi ``settings.captcha_secret`` set. Trong dev, để trống thì
``verify_captcha`` raise nothing và return True. Khi enforce mà token
thiếu/sai → raise HTTPException 400.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import HTTPException, status

from packages.config.settings import get_settings

logger = logging.getLogger(__name__)

_TURNSTILE_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
_HCAPTCHA_URL = "https://hcaptcha.com/siteverify"


async def verify_captcha(token: str | None, *, remote_ip: str | None = None) -> bool:
    """Verify Turnstile/hCaptcha token. Trả True nếu pass.

    Khi `captcha_secret` rỗng → coi như tắt (return True). Đây là behaviour
    mặc định cho dev/local; production cần set secret để enforce.
    """
    settings = get_settings()
    secret = settings.captcha_secret
    if not secret:
        return True
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="captcha required",
        )
    url = _TURNSTILE_URL if settings.captcha_provider == "turnstile" else _HCAPTCHA_URL
    data = {"secret": secret, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(url, data=data)
            payload = res.json()
    except Exception:  # noqa: BLE001
        logger.exception("captcha_verify_request_failed")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="captcha verification unavailable",
        ) from None
    if not payload.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="captcha invalid",
        )
    return True


def captcha_public_config() -> dict[str, str | bool]:
    """Trả config public cho FE (site_key + provider). Không expose secret."""
    settings = get_settings()
    return {
        "enabled": bool(settings.captcha_secret),
        "provider": settings.captcha_provider,
        "site_key": settings.captcha_site_key,
    }


__all__ = ["verify_captcha", "captcha_public_config"]
