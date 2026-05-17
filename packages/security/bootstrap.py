from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from packages.config.settings import get_settings
from packages.db.models import ApiKey
from packages.security.api_keys import generate_api_key, hash_api_key


async def create_api_key(
    session: AsyncSession,
    *,
    owner_id: str = "default",
    scopes: list[str] | None = None,
) -> tuple[str, ApiKey]:
    raw_key = generate_api_key()
    digest = hash_api_key(raw_key, salt=get_settings().api_key_salt)
    record = ApiKey(owner_id=owner_id, key_hash=digest, scopes=scopes or ["orders:write"])
    session.add(record)
    await session.flush()
    return raw_key, record
