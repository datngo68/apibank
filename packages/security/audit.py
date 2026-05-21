from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import AuditLog
from packages.security.pii import encrypt_pii_dict

# Target type chứa PII nhạy cảm — encrypt before_json/after_json khi setting bật.
_PII_TARGET_TYPES = {"user", "bank_account", "api_key"}


async def record_audit(
    session: AsyncSession,
    *,
    actor: str,
    action: str,
    target_type: str,
    target_id: str,
    ip: str | None = None,
    user_agent: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditLog:
    if target_type in _PII_TARGET_TYPES:
        before = encrypt_pii_dict(before)
        after = encrypt_pii_dict(after)
    log = AuditLog(
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        ip=ip,
        user_agent=user_agent,
        before_json=before,
        after_json=after,
    )
    session.add(log)
    return log
