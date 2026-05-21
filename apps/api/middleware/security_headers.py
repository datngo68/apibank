"""Security headers + request id middleware.

Áp dụng:
- Strict-Transport-Security (chỉ khi HTTPS hoặc env=production)
- Content-Security-Policy: hạn chế nguồn script/style
- X-Frame-Options: DENY
- X-Content-Type-Options: nosniff
- Referrer-Policy: strict-origin-when-cross-origin
- Permissions-Policy: tắt những API không dùng (camera, mic, geo)
- X-Request-Id: gắn UUID cho mọi request, để dễ trace log

CSP nới lỏng cho `'unsafe-inline'` style (Tailwind có một số inline minor) và
script-src 'self'. Khi Vite dev (cổng 5173) gọi sang API, header được giữ.
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from typing import Any

import sentry_sdk
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from packages.obs.context import request_id_var, route_var, user_id_var


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    # Ghi chú CSP:
    # - SPA React đã build → KHÔNG cần `unsafe-inline` script.
    # - cdn.tailwindcss.com / unpkg.com: legacy admin Jinja templates dùng nonce.
    #   Khi không gen nonce thì admin templates sẽ không chạy script inline —
    #   chấp nhận tradeoff cho SPA strict; admin Jinja đang phase-out.
    # - static.cloudflareinsights.com + cloudflareinsights.com: Cloudflare beacon.
    DEFAULT_CSP = (
        "default-src 'self'; "
        "script-src 'self' https://challenges.cloudflare.com https://js.hcaptcha.com "
        "https://static.cloudflareinsights.com; "
        "script-src-elem 'self' https://challenges.cloudflare.com "
        "https://js.hcaptcha.com https://static.cloudflareinsights.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data: blob: https://img.vietqr.io; "
        "connect-src 'self' https://cloudflareinsights.com "
        "https://challenges.cloudflare.com https://hcaptcha.com; "
        "frame-src https://challenges.cloudflare.com https://hcaptcha.com "
        "https://*.hcaptcha.com; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )

    def __init__(
        self,
        app: Any,
        *,
        environment: str = "local",
        csp: str | None = None,
        request_id_header: str = "X-Request-Id",
    ) -> None:
        super().__init__(app)
        self._csp = csp or self.DEFAULT_CSP
        self._is_prod = environment.lower() in {"production", "prod"}
        self._request_id_header = request_id_header

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get(self._request_id_header) or _new_request_id()
        request.state.request_id = request_id
        rid_token = request_id_var.set(request_id)
        # Best-effort lấy user_id từ session middleware đã chạy trước đó
        sess_user = None
        try:
            sess_user = request.session.get("user_id") if hasattr(request, "session") else None
        except Exception:  # noqa: BLE001
            sess_user = None
        uid_token = user_id_var.set(sess_user)
        sentry_sdk.set_tag("request_id", request_id)
        if sess_user:
            sentry_sdk.set_user({"id": sess_user})
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(rid_token)
            user_id_var.reset(uid_token)
            # route được set lại ở http_metrics middleware sau khi route match;
            # context var không cần cleanup vì sẽ được middleware reset mỗi req.
            route_var.set(None)
        response.headers.setdefault(self._request_id_header, request_id)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), interest-cohort=()",
        )
        response.headers.setdefault("Content-Security-Policy", self._csp)
        if self._is_prod:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=63072000; includeSubDomains; preload",
            )
        return response


def _new_request_id() -> str:
    return secrets.token_hex(16)
