from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, cast

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.config.settings import get_settings
from packages.db.models import BankAccount
from packages.db.session import get_session

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

    body = {"status": "ready" if overall_ok else "degraded", "components": components}
    return JSONResponse(content=body, status_code=200 if overall_ok else 503)
