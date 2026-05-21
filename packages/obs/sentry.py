from __future__ import annotations

from typing import Any

import sentry_sdk

from packages.config.settings import get_settings

# Field bị strip khỏi Sentry event để tránh leak secret/PII.
_REDACTED_KEYS = {
    "password",
    "password_hash",
    "secret",
    "secret_enc",
    "credentials_enc",
    "client_secret",
    "bot_token",
    "raw_key",
    "key_hash",
    "authorization",
    "cookie",
    "csrf",
    "api_key",
    "apikey",
}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("***" if k.lower() in _REDACTED_KEYS else _redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def _before_send(event: Any, hint: dict[str, Any]) -> Any:
    # Xoá body request có khả năng chứa mật khẩu/token.
    if not isinstance(event, dict):
        return event
    request = event.get("request") or {}
    if isinstance(request, dict):
        if "data" in request:
            request["data"] = "***"
        if "cookies" in request:
            request["cookies"] = "***"
        headers = request.get("headers")
        if isinstance(headers, dict):
            for h in list(headers):
                if h.lower() in _REDACTED_KEYS:
                    headers[h] = "***"
        event["request"] = request
    extra = event.get("extra")
    if isinstance(extra, dict):
        event["extra"] = _redact(extra)
    return event


def init_sentry(*, component: str) -> None:
    settings = get_settings()
    if not settings.sentry_dsn:
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        release=f"apibank@{settings.app_name}",
        traces_sample_rate=0.1,
        profiles_sample_rate=0.1,
        send_default_pii=False,
        max_breadcrumbs=50,
        attach_stacktrace=True,
        before_send=_before_send,
    )
    sentry_sdk.set_tag("component", component)
