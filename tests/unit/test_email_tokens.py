"""Unit tests cho email tokens (verify, reset)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import User
from packages.security.email_tokens import (
    KIND_RESET,
    KIND_VERIFY,
    consume_email_token,
    issue_email_token,
)
from packages.security.passwords import hash_password


async def _make_user(session: AsyncSession, email: str = "u@a.com") -> User:
    user = User(email=email, password_hash=hash_password("x" * 8), full_name="U", role="user")
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_issue_and_consume_verify_token(initialized_db: AsyncSession) -> None:
    user = await _make_user(initialized_db)
    raw, _ = await issue_email_token(initialized_db, user, KIND_VERIFY)
    await initialized_db.commit()

    consumed = await consume_email_token(initialized_db, raw, KIND_VERIFY)
    assert consumed is not None and consumed.id == user.id


@pytest.mark.asyncio
async def test_token_single_use(initialized_db: AsyncSession) -> None:
    user = await _make_user(initialized_db)
    raw, _ = await issue_email_token(initialized_db, user, KIND_RESET)
    await initialized_db.commit()
    assert await consume_email_token(initialized_db, raw, KIND_RESET) is not None
    await initialized_db.commit()
    # Lần thứ 2 phải fail
    assert await consume_email_token(initialized_db, raw, KIND_RESET) is None


@pytest.mark.asyncio
async def test_kind_must_match(initialized_db: AsyncSession) -> None:
    user = await _make_user(initialized_db)
    raw, _ = await issue_email_token(initialized_db, user, KIND_VERIFY)
    await initialized_db.commit()
    # Dùng đúng kind khác → phải None
    assert await consume_email_token(initialized_db, raw, KIND_RESET) is None


@pytest.mark.asyncio
async def test_expired_token_rejected(initialized_db: AsyncSession) -> None:
    user = await _make_user(initialized_db)
    raw, record = await issue_email_token(
        initialized_db, user, KIND_RESET, ttl=timedelta(seconds=1)
    )
    record.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await initialized_db.commit()
    assert await consume_email_token(initialized_db, raw, KIND_RESET) is None


@pytest.mark.asyncio
async def test_invalid_token_rejected(initialized_db: AsyncSession) -> None:
    user = await _make_user(initialized_db)
    await issue_email_token(initialized_db, user, KIND_VERIFY)
    await initialized_db.commit()
    assert await consume_email_token(initialized_db, "no-such-token", KIND_VERIFY) is None


@pytest.mark.asyncio
async def test_locked_user_token_rejected(initialized_db: AsyncSession) -> None:
    user = await _make_user(initialized_db)
    raw, _ = await issue_email_token(initialized_db, user, KIND_RESET)
    user.status = "locked"
    await initialized_db.commit()
    assert await consume_email_token(initialized_db, raw, KIND_RESET) is None
