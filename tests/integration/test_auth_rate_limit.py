"""Tests cho rate-limit per-email + lockout exponential ở /login.

Verify:
- 10 hits / 60s / email vào /login đẩy hit thứ 11 thành 429.
- Lockout exponential không reset count khi đạt threshold.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest


@pytest.fixture
def app_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    db_path = tmp_path / "rl.db"
    monkeypatch.setenv("APIBANK_DB_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("APIBANK_FERNET_KEYS", "")
    monkeypatch.setenv("APIBANK_API_KEY_SALT", "test-salt")
    monkeypatch.setenv("APIBANK_LOG_LEVEL", "WARNING")
    yield


@pytest.fixture
async def client(app_env: None) -> AsyncIterator[httpx.AsyncClient]:
    import packages.db.session as session_module
    from packages.config.settings import get_settings

    get_settings.cache_clear()
    session_module._engine = None
    session_module._sessionmaker = None
    from packages.db.models import Base

    engine = session_module.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Reset auth-rate-limit state giữa các test (singleton in-memory).
    from apps.api.routes import auth as auth_module

    auth_module._auth_email_limiter = type(auth_module._auth_email_limiter)(
        capacity=auth_module._AUTH_RL_CAPACITY, window_seconds=60
    )

    from apps.api.main import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        await ac.get("/healthz")
        yield ac
    await engine.dispose()
    session_module._engine = None
    session_module._sessionmaker = None


def _csrf(client: httpx.AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("apibank_csrf", "")}


@pytest.mark.asyncio
async def test_login_rate_limit_per_email_returns_429(
    client: httpx.AsyncClient,
) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "rl@e.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    # Chiếm trọn 10 slot rate-limit (mỗi hit fail vì password sai).
    for i in range(10):
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "rl@e.com", "password": f"wrong-{i}"},
            headers=_csrf(client),
        )
        # Đầu tiên là 401, đến lần 5 sẽ 423 (locked) — nhưng cả hai đều OK,
        # quan trọng là bucket auth tăng. (Test dùng email khác cho lockout case.)
        assert r.status_code in (401, 423)

    eleventh = await client.post(
        "/api/v1/auth/login",
        json={"email": "rl@e.com", "password": "anything"},
        headers=_csrf(client),
    )
    assert eleventh.status_code == 429, eleventh.text


@pytest.mark.asyncio
async def test_lockout_does_not_reset_failed_count(
    client: httpx.AsyncClient,
) -> None:
    """Sau 5 lần sai → user lock và `failed_login_count` >= 5 (không reset 0)."""
    from sqlalchemy import select

    import packages.db.session as session_module
    from packages.db.models import User

    await client.post(
        "/api/v1/auth/register",
        json={"email": "lock-exp@e.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    for i in range(5):
        await client.post(
            "/api/v1/auth/login",
            json={"email": "lock-exp@e.com", "password": f"bad-{i}"},
            headers=_csrf(client),
        )

    sm = session_module.get_sessionmaker()
    async with sm() as s:
        user = (await s.scalars(select(User).where(User.email == "lock-exp@e.com"))).first()
        assert user is not None
        # Bug cũ reset về 0 sau lock — fix đảm bảo >= threshold.
        assert user.failed_login_count >= 5
        assert user.locked_until is not None
        locked = user.locked_until
        if locked.tzinfo is None:
            locked = locked.replace(tzinfo=UTC)
        assert locked > datetime.now(UTC)


@pytest.mark.asyncio
async def test_register_rate_limit(client: httpx.AsyncClient) -> None:
    """Spam /register cùng email → 429 sau 10 lần."""
    for _ in range(10):
        r = await client.post(
            "/api/v1/auth/register",
            json={"email": "spam@e.com", "password": "Strong-Pass-1"},
            headers=_csrf(client),
        )
        # Lần 1: 201 thật; các lần sau: 201 generic (anti-enum).
        assert r.status_code == 201

    eleventh = await client.post(
        "/api/v1/auth/register",
        json={"email": "spam@e.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    assert eleventh.status_code == 429
    _ = time  # silence unused if test doesn't use it
