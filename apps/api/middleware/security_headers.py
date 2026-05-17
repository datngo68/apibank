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

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    # Ghi chú CSP:
    # - cdn.tailwindcss.com / unpkg.com: dùng cho admin templates Jinja.
    # - static.cloudflareinsights.com + cloudflareinsights.com: Cloudflare tunnel/CDN
    #   tự động inject `beacon.min.js` cho Web Analytics; không thêm sẽ bị block khi
    #   chạy sau trycloudflare/ngrok/cloudflare proxy.
    # - img-src cho phép cùng origin (qr/pay PNG) + img.vietqr.io (legacy admin).
    DEFAULT_CSP = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com "
        "https://unpkg.com https://static.cloudflareinsights.com; "
        "script-src-elem 'self' 'unsafe-inline' https://cdn.tailwindcss.com "
        "https://unpkg.com https://static.cloudflareinsights.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com "
        "https://cdn.tailwindcss.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data: blob: https://img.vietqr.io; "
        "connect-src 'self' https://cloudflareinsights.com; "
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
        response = await call_next(request)
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
