"""Server-side session quản lý phiên đăng nhập user qua bảng `sessions`.

Khác biệt so với JWT:
- Có thể revoke tức thì (đặt `revoked_at`).
- Chỉ lưu hash của token; gốc gửi về client qua cookie httpOnly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import Session as SessionModel
from packages.db.models import User
from packages.security.tokens import generate_token, hash_token

DEFAULT_TTL = timedelta(days=30)
COOKIE_NAME = "apibank_sid"


async def issue_session(
    session: AsyncSession,
    user: User,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
    ttl: timedelta = DEFAULT_TTL,
) -> tuple[str, SessionModel]:
    """Tạo session, trả (raw_token, model). Gọi `session.commit()` ở caller."""
    raw = generate_token(48)
    now = datetime.now(UTC)
    record = SessionModel(
        user_id=user.id,
        token_hash=hash_token(raw),
        ip=ip,
        user_agent=(user_agent or "")[:512] or None,
        expires_at=now + ttl,
        created_at=now,
        last_seen_at=now,
    )
    session.add(record)
    await session.flush()
    return raw, record


async def lookup_session(
    session: AsyncSession,
    raw_token: str,
) -> tuple[SessionModel, User] | None:
    if not raw_token:
        return None
    digest = hash_token(raw_token)
    stmt = (
        select(SessionModel, User)
        .join(User, SessionModel.user_id == User.id)
        .where(SessionModel.token_hash == digest)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    sess, user = row
    if sess.revoked_at is not None:
        return None
    expires = sess.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires < datetime.now(UTC):
        return None
    if user.status != "active":
        return None
    return sess, user


async def touch_session(
    session: AsyncSession, sess: SessionModel, *, ip: str | None = None
) -> None:
    sess.last_seen_at = datetime.now(UTC)
    if ip:
        sess.ip = ip


async def revoke_session(session: AsyncSession, session_id: str) -> bool:
    now = datetime.now(UTC)
    result = await session.execute(
        update(SessionModel)
        .where(SessionModel.id == session_id)
        .where(SessionModel.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    return (result.rowcount or 0) > 0


async def revoke_all_sessions(session: AsyncSession, user_id: str, *, except_id: str | None = None) -> int:
    now = datetime.now(UTC)
    stmt = (
        update(SessionModel)
        .where(SessionModel.user_id == user_id)
        .where(SessionModel.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    if except_id is not None:
        stmt = stmt.where(SessionModel.id != except_id)
    result = await session.execute(stmt)
    return int(result.rowcount or 0)
