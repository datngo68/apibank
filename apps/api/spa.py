"""Mount SPA build (apps/web/dist) vào FastAPI app.

Quy tắc:
- `/assets/*`: static, cache-immutable 1 năm.
- `/index.html` & root SPA route: no-cache để đẩy bản mới ngay khi deploy.
- Fallback `GET /{path:path}`: nếu path không thuộc API/admin/healthz/qr/pay/metrics
  thì trả index.html để React Router xử lý client-side routing.

Phải gọi `mount_spa(app)` sau khi đã include tất cả router API/admin để fallback
không nuốt request hợp lệ.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, status
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

logger = logging.getLogger(__name__)

WEB_DIST = Path(__file__).resolve().parents[1] / "web" / "dist"
INDEX_HTML = WEB_DIST / "index.html"

# Path không bao giờ rơi vào SPA fallback
_API_PREFIXES: tuple[str, ...] = (
    "/api/",
    "/v1/",
    "/healthz",
    "/readyz",
    "/metrics",
    "/qr/",
    "/pay/",
    "/static/",
)


class CachingStaticFiles(StaticFiles):
    """Serve immutable assets với Cache-Control 1 năm."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code == status.HTTP_200_OK:
            response.headers.setdefault(
                "Cache-Control", "public, max-age=31536000, immutable"
            )
        return response


def mount_spa(app: FastAPI) -> bool:
    """Đăng ký SPA routes. Trả True nếu mount được, False nếu chưa build."""
    if not INDEX_HTML.exists():
        logger.warning(
            "spa_dist_missing",
            extra={"path": str(WEB_DIST)},
        )
        return False

    assets_dir = WEB_DIST / "assets"
    if assets_dir.is_dir():
        app.mount(
            "/assets",
            CachingStaticFiles(directory=str(assets_dir)),
            name="spa-assets",
        )

    # Static file đặt cạnh dist nhưng không trong /assets (vd. favicon.svg)
    @app.get("/favicon.svg", include_in_schema=False)
    async def favicon_svg() -> Response:
        path = WEB_DIST / "favicon.svg"
        if path.exists():
            return FileResponse(
                str(path),
                media_type="image/svg+xml",
                headers={"Cache-Control": "public, max-age=86400"},
            )
        return JSONResponse({"detail": "not found"}, status_code=404)

    @app.get("/", include_in_schema=False)
    async def spa_root() -> Response:
        return FileResponse(
            str(INDEX_HTML),
            media_type="text/html; charset=utf-8",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> Response:
        path = "/" + full_path
        # Không nuốt API/admin/healthz...
        if path.startswith(_API_PREFIXES) or any(
            path.startswith(p) for p in _API_PREFIXES
        ):
            return JSONResponse({"detail": "not found"}, status_code=404)
        # Static file thực tế (vd /robots.txt nếu có) — guard path traversal:
        # `WEB_DIST / full_path` không tự normalize `..`. Bắt buộc resolve và
        # check `is_relative_to(WEB_DIST)` trước khi serve.
        try:
            candidate = (WEB_DIST / full_path).resolve()
            if (
                candidate.is_relative_to(WEB_DIST.resolve())
                and candidate.is_file()
            ):
                return FileResponse(str(candidate))
        except (ValueError, OSError):
            pass
        # Fallback index.html cho client-side routing
        return FileResponse(
            str(INDEX_HTML),
            media_type="text/html; charset=utf-8",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    # Tránh "unused" cảnh báo
    _ = (favicon_svg, spa_root, spa_fallback)
    return True
