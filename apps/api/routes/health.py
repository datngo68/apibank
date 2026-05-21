from __future__ import annotations

import time
from collections.abc import Awaitable
from typing import Any, cast

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.config.settings import get_settings
from packages.db.models import BankAccount
from packages.db.session import get_session
from packages.obs import metrics
from packages.security.crypto import FernetCipher

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(session: AsyncSession = Depends(get_session)) -> JSONResponse:
    components: dict[str, str] = {}
    overall_ok = True

    try:
        await session.execute(text("SELECT 1"))
        components["db"] = "ok"
    except Exception as exc:
        components["db"] = f"fail: {exc!r}"
        overall_ok = False

    try:
        from redis.asyncio import Redis

        redis = Redis.from_url(get_settings().redis_url)
        await cast(Awaitable[Any], redis.ping())
        await redis.aclose()
        components["redis"] = "ok"
    except Exception as exc:
        components["redis"] = f"fail: {exc!r}"

    try:
        accounts = list(
            (
                await session.scalars(
                    select(BankAccount).where(BankAccount.polling_enabled.is_(True))
                )
            ).all()
        )
        components["bank_accounts_active"] = str(len(accounts))
    except Exception as exc:
        components["bank_accounts_active"] = f"fail: {exc!r}"
        overall_ok = False

    # Fernet smoke: thử encrypt+decrypt 1 chuỗi tĩnh để chắc keys còn rotate đúng.
    try:
        keys = get_settings().fernet_keys
        if keys:
            cipher = FernetCipher.from_keys(keys)
            cipher.decrypt(cipher.encrypt("ping"))
            components["fernet"] = "ok"
        else:
            components["fernet"] = "missing_keys"
    except Exception as exc:  # noqa: BLE001
        components["fernet"] = f"fail: {exc!r}"
        overall_ok = False

    # Scheduler heartbeat: kiểm tra last_run của job webhook (chạy mỗi 30s).
    try:
        # set_to_current_time đã ghi vào gauge; đọc qua _value của Gauge child.
        labels = metrics.scheduler_last_run_timestamp.labels(job="webhook")
        last_ts = float(labels._value.get() or 0.0)
        if last_ts <= 0.0:
            components["scheduler"] = "no_heartbeat_yet"
        else:
            age = max(0.0, time.time() - last_ts)
            if age > 180:
                components["scheduler"] = f"stale: {int(age)}s"
                overall_ok = False
            else:
                components["scheduler"] = "ok"
    except Exception as exc:  # noqa: BLE001
        components["scheduler"] = f"fail: {exc!r}"

    body = {"status": "ready" if overall_ok else "degraded", "components": components}
    return JSONResponse(content=body, status_code=200 if overall_ok else 503)
