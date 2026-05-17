"""Unit tests cho session lifecycle (issue/lookup/revoke)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import User
from packages.security.passwords import hash_password
from packages.security.sessions import (
    issue_session,
    lookup_session,
    revoke_all_sessions,
    revoke_session,
    touch_session,
)


async def _make_user(session: AsyncSession, *, email: str = "u@a.com") -> User:
    user = User(
        email=email,
        password_hash=hash_password("pwd-1234"),
        full_name="U",
        role="user",
        status="active",
    )
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_issue_and_lookup(initialized_db: AsyncSession) -> None:
    user = await _make_user(initialized_db)
    raw, sess = await issue_session(initialized_db, user, ip="1.2.3.4", user_agent="ua")
    await initialized_db.commit()
    assert raw and len(raw) >= 30
    assert sess.token_hash != raw

    pair = await lookup_session(initialized_db, raw)
    assert pair is not None
    assert pair[1].id == user.id


@pytest.mark.asyncio
async def test_lookup_unknown_returns_none(initialized_db: AsyncSession) -> None:
    assert await lookup_session(initialized_db, "missing") is None
    assert await lookup_session(initialized_db, "") is None


@pytest.mark.asyncio
async def test_revoked_session_not_returned(initialized_db: AsyncSession) -> None:
    user = await _make_user(initialized_db)
    raw, sess = await issue_session(initialized_db, user)
    await initialized_db.commit()

    assert await revoke_session(initialized_db, sess.id) is True
    await initialized_db.commit()
    assert await lookup_session(initialized_db, raw) is None


@pytest.mark.asyncio
async def test_expired_session_not_returned(initialized_db: AsyncSession) -> None:
    user = await _make_user(initialized_db)
    raw, sess = await issue_session(initialized_db, user, ttl=timedelta(seconds=1))
    sess.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await initialized_db.commit()
    assert await lookup_session(initialized_db, raw) is None


@pytest.mark.asyncio
async def test_inactive_user_not_returned(initialized_db: AsyncSession) -> None:
    user = await _make_user(initialized_db)
    raw, _ = await issue_session(initialized_db, user)
    user.status = "locked"
    await initialized_db.commit()
    assert await lookup_session(initialized_db, raw) is None


@pytest.mark.asyncio
async def test_revoke_all_sessions(initialized_db: AsyncSession) -> None:
    user = await _make_user(initialized_db)
    raw1, _ = await issue_session(initialized_db, user)
    raw2, sess2 = await issue_session(initialized_db, user)
    await initialized_db.commit()

    revoked = await revoke_all_sessions(initialized_db, user.id, except_id=sess2.id)
    await initialized_db.commit()
    assert revoked == 1
    assert await lookup_session(initialized_db, raw1) is None
    assert await lookup_session(initialized_db, raw2) is not None


@pytest.mark.asyncio
async def test_touch_updates_last_seen(initialized_db: AsyncSession) -> None:
    user = await _make_user(initialized_db)
    _, sess = await issue_session(initialized_db, user)
    await initialized_db.commit()
    before = sess.last_seen_at
    await touch_session(initialized_db, sess, ip="9.9.9.9")
    await initialized_db.commit()
    assert sess.last_seen_at >= before
    assert sess.ip == "9.9.9.9"
