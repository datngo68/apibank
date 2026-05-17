from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import AuditLog


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
