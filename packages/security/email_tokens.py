"""Email tokens cho verify-email, password reset, change email.

Token plain chỉ tồn tại trong link gửi qua email; DB lưu hash. Mỗi token là single-use,
có TTL và gắn với 1 user.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import EmailToken, User
from packages.security.tokens import generate_token, hash_token

KIND_VERIFY = "verify"
KIND_RESET = "reset"
KIND_CHANGE_EMAIL = "change_email"

DEFAULT_TTL: dict[str, timedelta] = {
    KIND_VERIFY: timedelta(days=2),
    KIND_RESET: timedelta(hours=1),
    KIND_CHANGE_EMAIL: timedelta(hours=2),
}


async def issue_email_token(
    session: AsyncSession,
    user: User,
    kind: str,
    *,
    ttl: timedelta | None = None,
) -> tuple[str, EmailToken]:
    raw = generate_token(32)
    now = datetime.now(UTC)
    record = EmailToken(
        user_id=user.id,
        kind=kind,
        token_hash=hash_token(raw),
        expires_at=now + (ttl or DEFAULT_TTL.get(kind, timedelta(hours=1))),
        created_at=now,
    )
    session.add(record)
    await session.flush()
    return raw, record


async def consume_email_token(
    session: AsyncSession, raw_token: str, kind: str
) -> User | None:
    """Tìm token; nếu hợp lệ — đánh dấu used và trả User. Nếu không hợp lệ — None."""
    digest = hash_token(raw_token)
    stmt = (
        select(EmailToken)
        .where(EmailToken.token_hash == digest)
        .where(EmailToken.kind == kind)
    )
    record = (await session.scalars(stmt)).first()
    if record is None:
        return None
    now = datetime.now(UTC)
    expires = record.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if record.used_at is not None or expires < now:
        return None
    record.used_at = now
    user = await session.get(User, record.user_id)
    if user is None or user.status != "active":
        return None
    return user
