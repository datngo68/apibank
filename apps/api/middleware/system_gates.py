"""Middleware enforce maintenance mode + IP blocklist (admin toggle).

Maintenance: nếu ``AppConfig.key='maintenance'`` có ``enabled=True``, mọi
request trừ ``/api/v1/admin/*``, ``/healthz``, ``/readyz``, ``/auth/login``
trả 503. Admin vẫn vào được để toggle off.

IP blocklist: kiểm CIDR trong bảng ``ip_blocklist`` (cache 60s) trước khi
process request → trả 403.
"""

from __future__ import annotations

import ipaddress
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from packages.config import runtime as config_runtime
from packages.db.session import get_sessionmaker

logger = logging.getLogger(__name__)


class MaintenanceMiddleware(BaseHTTPMiddleware):
    """Trả 503 khi maintenance bật (ngoại trừ admin/healthz)."""

    BYPASS_PREFIX = (
        "/api/v1/admin/",
        "/api/v1/auth/login",
        "/api/v1/auth/me",
        "/api/v1/auth/logout",
        "/healthz",
        "/readyz",
        "/metrics",
    )

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path
        if any(path.startswith(p) for p in self.BYPASS_PREFIX):
            return await call_next(request)
        try:
            sessionmaker = get_sessionmaker()
            async with sessionmaker() as session:
                cfg = await config_runtime.get_config(session, "maintenance")
        except Exception:  # noqa: BLE001
            return await call_next(request)
        if cfg.get("enabled"):
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "detail": "maintenance",
                    "message": cfg.get("message", "Hệ thống đang bảo trì"),
                },
            )
        return await call_next(request)


class IpBlocklistMiddleware(BaseHTTPMiddleware):
    """Chặn IP nằm trong ip_blocklist. Cache 60s để tránh query DB mỗi req."""

    _CACHE_TTL = 60.0

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self._cache: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        self._cache_at: float = 0.0

    async def _load(self) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
        if time.monotonic() - self._cache_at < self._CACHE_TTL:
            return self._cache
        try:
            from sqlalchemy import select

            from packages.db.models import IpBlocklist

            sessionmaker = get_sessionmaker()
            async with sessionmaker() as session:
                rows = list((await session.scalars(select(IpBlocklist))).all())
            nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
            for r in rows:
                try:
                    nets.append(ipaddress.ip_network(r.cidr, strict=False))
                except ValueError:
                    continue
            self._cache = nets
            self._cache_at = time.monotonic()
        except Exception:  # noqa: BLE001
            # DB chưa migrate / lỗi → bỏ qua, không chặn request.
            self._cache = []
            self._cache_at = time.monotonic()
        return self._cache

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        host = request.client.host if request.client else None
        if not host:
            return await call_next(request)
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return await call_next(request)
        nets = await self._load()
        for net in nets:
            if ip in net:
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": "ip blocked"},
                )
        return await call_next(request)


__all__ = ["MaintenanceMiddleware", "IpBlocklistMiddleware"]
