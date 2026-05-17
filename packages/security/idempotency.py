from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import ApiKey, IdempotencyKey
from packages.security.api_keys import hash_api_key


async def resolve_api_key(session: AsyncSession, *, raw_key: str, salt: str) -> ApiKey | None:
    digest = hash_api_key(raw_key, salt=salt)
    result = await session.scalars(
        select(ApiKey).where(ApiKey.key_hash == digest).where(ApiKey.revoked_at.is_(None))
    )
    return result.first()


async def reuse_or_create_idempotent_response(
    session: AsyncSession,
    *,
    api_key_id: str,
    key: str,
    request_hash: str,
) -> IdempotencyKey | None:
    existing = (
        await session.scalars(
            select(IdempotencyKey).where(
                IdempotencyKey.api_key_id == api_key_id,
                IdempotencyKey.key == key,
            )
        )
    ).first()
    if existing is None:
        return None
    if existing.request_hash != request_hash:
        raise ValueError("idempotency key reused with different request body")
    return existing


def build_idempotency_record(
    *,
    api_key_id: str,
    key: str,
    request_hash: str,
    response_payload: dict[str, Any],
    ttl_hours: int = 24,
) -> IdempotencyKey:
    return IdempotencyKey(
        key=key,
        api_key_id=api_key_id,
        request_hash=request_hash,
        response_json=response_payload,
        expires_at=datetime.now(UTC) + timedelta(hours=ttl_hours),
    )
