"""Usage metering middleware — đếm request /v1/* theo day×user×api_key×endpoint.

Per-process accumulator + flush mỗi 60s vào ``api_usage_daily`` qua upsert
(ON CONFLICT DO UPDATE). Best-effort: lỗi DB không cản trở response — chỉ log.

Chỉ đếm request có ``request.state.api_key_id`` (set bởi
``packages.security.dependencies.authenticated_api_key``). Không đếm:
- /healthz, /readyz, /metrics
- /api/v1/admin/*, /api/v1/me/* (cookie session, không phải API key)
- SSE /events long-lived
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from fastapi import Request, Response
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from starlette.middleware.base import BaseHTTPMiddleware

from packages.db.models import ApiUsageDaily
from packages.db.session import get_engine, get_sessionmaker

logger = logging.getLogger(__name__)

_FLUSH_INTERVAL_SECONDS = 60.0


def classify_endpoint(path: str, method: str) -> str:
    """Rút gọn path → endpoint_group cố định để hạn chế cardinality.

    Chỉ care path /v1/* (path public API). Các path khác trả ``other``
    (middleware skip không log nhưng giữ logic phòng khi gọi trực tiếp).
    """
    if not path.startswith("/v1/"):
        return "other"
    seg = path[len("/v1/"):].split("/", 1)[0]
    if seg == "orders":
        # POST /v1/orders → create; GET /v1/orders/{id} hoặc /v1/orders → read
        return "orders.create" if method == "POST" else "orders.read"
    if seg == "transactions":
        return "transactions.list"
    if seg == "webhooks":
        return "webhooks." + (method.lower() if method else "other")
    if seg == "bank-accounts":
        return "bank_accounts." + (method.lower() if method else "other")
    return f"v1.{seg}"


class UsageMeteringMiddleware(BaseHTTPMiddleware):
    """Accumulator in-memory + background flush task.

    Singleton-ish: chỉ nên đăng ký 1 instance. Worker khác process có
    accumulator riêng, mỗi flush upsert riêng — nhờ ON CONFLICT cộng dồn
    chính xác.
    """

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        # Key: (day_iso, user_id, api_key_id, endpoint_group)
        # Value: [count, error_count]
        self._buffer: dict[tuple[str, str, str, str], list[int]] = {}
        self._lock = Lock()
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def _ensure_task(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(
                self._flush_loop(), name="usage-metering-flush"
            )

    async def _flush_loop(self) -> None:
        try:
            while not self._stop.is_set():
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._stop.wait(), timeout=_FLUSH_INTERVAL_SECONDS
                    )
                await self._flush()
        except asyncio.CancelledError:
            await self._flush()
            raise

    async def _flush(self) -> None:
        with self._lock:
            if not self._buffer:
                return
            snapshot = self._buffer
            self._buffer = {}

        try:
            sessionmaker = get_sessionmaker()
            engine = get_engine()
            dialect = engine.dialect.name
            now = datetime.now(UTC)
            async with sessionmaker() as session:
                for (day_iso, user_id, api_key_id, group), (cnt, err) in snapshot.items():
                    day = datetime.fromisoformat(day_iso).date()
                    values = {
                        "day": day,
                        "user_id": user_id,
                        "api_key_id": api_key_id,
                        "endpoint_group": group,
                        "count": cnt,
                        "error_count": err,
                        "updated_at": now,
                    }
                    if dialect == "postgresql":
                        pg_stmt = pg_insert(ApiUsageDaily).values(**values)
                        pg_stmt = pg_stmt.on_conflict_do_update(
                            index_elements=[
                                "day", "user_id", "api_key_id", "endpoint_group",
                            ],
                            set_={
                                "count": ApiUsageDaily.count + pg_stmt.excluded.count,
                                "error_count": (
                                    ApiUsageDaily.error_count
                                    + pg_stmt.excluded.error_count
                                ),
                                "updated_at": pg_stmt.excluded.updated_at,
                            },
                        )
                        await session.execute(pg_stmt)
                    elif dialect == "sqlite":
                        sq_stmt = sqlite_insert(ApiUsageDaily).values(**values)
                        sq_stmt = sq_stmt.on_conflict_do_update(
                            index_elements=[
                                "day", "user_id", "api_key_id", "endpoint_group",
                            ],
                            set_={
                                "count": ApiUsageDaily.count + sq_stmt.excluded.count,
                                "error_count": (
                                    ApiUsageDaily.error_count
                                    + sq_stmt.excluded.error_count
                                ),
                                "updated_at": sq_stmt.excluded.updated_at,
                            },
                        )
                        await session.execute(sq_stmt)
                    else:
                        # Generic fallback: SELECT then INSERT/UPDATE
                        existing = await session.get(
                            ApiUsageDaily,
                            (day, user_id, api_key_id, group),
                        )
                        if existing is None:
                            session.add(ApiUsageDaily(**values))
                        else:
                            existing.count = (existing.count or 0) + cnt
                            existing.error_count = (existing.error_count or 0) + err
                            existing.updated_at = now
                await session.commit()
        except Exception:  # noqa: BLE001
            logger.exception("usage_metering_flush_failed")
            # Đẩy lại vào buffer để retry tick sau (best-effort, không guarantee)
            with self._lock:
                for k, (cnt, err) in snapshot.items():
                    if k in self._buffer:
                        self._buffer[k][0] += cnt
                        self._buffer[k][1] += err
                    else:
                        self._buffer[k] = [cnt, err]

    async def shutdown(self) -> None:
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except (TimeoutError, asyncio.CancelledError):
                self._task.cancel()
        await self._flush()

    def _record(self, request: Request, status_code: int) -> None:
        api_key_id = getattr(request.state, "api_key_id", None)
        if not api_key_id:
            return
        user_id = getattr(request.state, "user_id", None) or ""
        path = request.url.path
        if not path.startswith("/v1/"):
            return
        group = classify_endpoint(path, request.method)
        # Use UTC date as bucket
        day_iso = datetime.now(UTC).date().isoformat()
        key = (day_iso, user_id, api_key_id, group)
        is_error = 1 if status_code >= 400 else 0
        with self._lock:
            if key in self._buffer:
                self._buffer[key][0] += 1
                self._buffer[key][1] += is_error
            else:
                self._buffer[key] = [1, is_error]

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        await self._ensure_task()
        path = request.url.path
        # Quick skip cho path không bao giờ được đếm để khỏi phải resolve user.
        if (
            path.startswith("/healthz")
            or path.startswith("/readyz")
            or path.startswith("/metrics")
            or path.startswith("/api/")
            or not path.startswith("/v1/")
        ):
            return await call_next(request)
        response = await call_next(request)
        try:
            self._record(request, response.status_code)
        except Exception:  # noqa: BLE001
            logger.exception("usage_metering_record_failed")
        return response


# Một số test/script muốn dùng helper để tự flush ngay (không qua middleware).
async def flush_usage_now(middleware: UsageMeteringMiddleware) -> None:
    """Force flush — dùng trong test."""
    await middleware._flush()
