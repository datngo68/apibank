"""CSRF double-submit cookie + middleware.

- Mỗi request không phải GET/HEAD/OPTIONS phải kèm header `X-CSRF-Token`
  khớp với cookie `apibank_csrf`. Cookie không httpOnly để JS đọc được; SameSite=Lax.
- Endpoint dùng API key (Bearer) bypass CSRF — bản thân Bearer đã chống CSRF.
- Endpoint public marketing/auth (POST /auth/login đầu tiên) cần header để chống CSRF
  cross-site; khi user vào trang lần đầu, server set cookie csrf qua middleware.
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

CSRF_COOKIE = "apibank_csrf"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
EXEMPT_PREFIXES = (
    "/healthz",
    "/readyz",
    "/metrics",
    "/qr/",
    "/pay/",
    "/v1/",  # public API key endpoints chống CSRF bằng Bearer header
    "/api/v1/telegram/webhook",  # Telegram POST webhook, verify bằng secret_token header
)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


class CsrfMiddleware(BaseHTTPMiddleware):
    """Set cookie nếu thiếu; verify header khớp cookie cho mọi unsafe method.

    Endpoint /api/* (auth, me) sẽ chạy qua middleware này. Endpoint public API
    (/v1/*, dùng Bearer) được skip.
    """

    def __init__(self, app, *, cookie_name: str = CSRF_COOKIE, secure: bool = False) -> None:
        super().__init__(app)
        self._cookie_name = cookie_name
        self._secure = secure

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        method = request.method.upper()
        skip = method in SAFE_METHODS or any(path.startswith(p) for p in EXEMPT_PREFIXES)

        if not skip:
            cookie_value = request.cookies.get(self._cookie_name, "")
            header_value = request.headers.get(CSRF_HEADER, "")
            if not cookie_value or not header_value or not secrets.compare_digest(
                cookie_value, header_value
            ):
                return JSONResponse(
                    {"detail": "csrf token mismatch"}, status_code=status.HTTP_403_FORBIDDEN
                )

        response = await call_next(request)

        # Đảm bảo client luôn có cookie CSRF (rotate nhẹ — không rotate mỗi request).
        if self._cookie_name not in request.cookies:
            response.set_cookie(
                self._cookie_name,
                generate_csrf_token(),
                max_age=60 * 60 * 24 * 7,
                samesite="lax",
                secure=self._secure,
                httponly=False,
                path="/",
            )
        return response
