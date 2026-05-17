"""Integration tests for user-side Telegram link flow."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest


@pytest.fixture
def app_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    db_path = tmp_path / "user_tg.db"
    monkeypatch.setenv("APIBANK_DB_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv(
        "APIBANK_FERNET_KEYS",
        "primary:NhnFbDTpYks-q2AmJsBhuG_iL6VDaKL14L4vy44ZqkM=",
    )
    monkeypatch.setenv("APIBANK_API_KEY_SALT", "test-salt")
    monkeypatch.setenv("APIBANK_LOG_LEVEL", "WARNING")
    yield


@pytest.fixture
async def client(app_env: None) -> AsyncIterator[httpx.AsyncClient]:
    import packages.db.session as session_module
    from packages.config import runtime as runtime_module
    from packages.config.settings import get_settings

    get_settings.cache_clear()
    session_module._engine = None
    session_module._sessionmaker = None
    runtime_module.invalidate()

    from packages.db.models import Base

    engine = session_module.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed Telegram config (enabled + bot_token + bot_username) trước khi server start
    sm = session_module.get_sessionmaker()
    async with sm() as s:
        await runtime_module.set_config(
            s,
            "telegram",
            {
                "enabled": True,
                "bot_token": "123456:fake-token",
                "bot_username": "apibank_test_bot",
            },
            actor_id="seed",
            encrypt_fields=("bot_token",),
        )
        await s.commit()

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


async def _register_login(client: httpx.AsyncClient, email: str = "u@a.com") -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )


@pytest.mark.asyncio
async def test_link_chat_returns_deep_link(client: httpx.AsyncClient) -> None:
    await _register_login(client)
    res = await client.post(
        "/api/v1/auth/profile/telegram/link-chat", headers=_csrf(client)
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["deep_link_url"].startswith("https://t.me/apibank_test_bot?start=")
    assert body["expires_in"] == 600
    assert body["token"]


@pytest.mark.asyncio
async def test_link_chat_requires_auth(client: httpx.AsyncClient) -> None:
    res = await client.post(
        "/api/v1/auth/profile/telegram/link-chat", headers=_csrf(client)
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_link_chat_503_when_telegram_disabled(
    client: httpx.AsyncClient,
) -> None:
    """Disable telegram trong DB → endpoint trả 503."""
    import packages.db.session as session_module
    from packages.config import runtime as runtime_module

    sm = session_module.get_sessionmaker()
    async with sm() as s:
        await runtime_module.set_config(
            s,
            "telegram",
            {"enabled": False, "bot_username": "apibank_test_bot"},
            actor_id="seed",
            encrypt_fields=("bot_token",),
        )
        await s.commit()
    runtime_module.invalidate()

    await _register_login(client)
    res = await client.post(
        "/api/v1/auth/profile/telegram/link-chat", headers=_csrf(client)
    )
    assert res.status_code == 503


@pytest.mark.asyncio
async def test_webhook_consumes_user_token_and_sets_chat_id(
    client: httpx.AsyncClient,
) -> None:
    """Simulate Telegram POST webhook với /start <token> → user.telegram_chat_id được set."""
    from sqlalchemy import select

    import packages.db.session as session_module
    from packages.db.models import User
    from packages.notifications import telegram as tg_pkg

    await _register_login(client)
    # Sinh token
    res = await client.post(
        "/api/v1/auth/profile/telegram/link-chat", headers=_csrf(client)
    )
    raw_token = res.json()["token"]

    # Patch send_telegram để không gọi httpx thật
    async def _noop(*args, **kwargs):  # type: ignore[no-untyped-def]
        return True

    real_send = tg_pkg.send_telegram
    tg_pkg.send_telegram = _noop  # type: ignore[assignment]
    try:
        webhook_res = await client.post(
            "/api/v1/telegram/webhook",
            json={
                "update_id": 1,
                "message": {
                    "message_id": 1,
                    "chat": {"id": 999888, "type": "private"},
                    "text": f"/start {raw_token}",
                },
            },
        )
        assert webhook_res.status_code == 200, webhook_res.text
    finally:
        tg_pkg.send_telegram = real_send  # type: ignore[assignment]

    # Verify user đã được set chat_id
    sm = session_module.get_sessionmaker()
    async with sm() as s:
        u = (await s.scalars(select(User).where(User.email == "u@a.com"))).first()
        assert u is not None
        assert u.telegram_chat_id == "999888"


@pytest.mark.asyncio
async def test_unlink_removes_chat_id(client: httpx.AsyncClient) -> None:
    from sqlalchemy import select

    import packages.db.session as session_module
    from packages.db.models import User

    await _register_login(client)
    sm = session_module.get_sessionmaker()
    async with sm() as s:
        user = (await s.scalars(select(User).where(User.email == "u@a.com"))).first()
        assert user is not None
        user.telegram_chat_id = "111222"
        await s.commit()

    res = await client.delete(
        "/api/v1/auth/profile/telegram", headers=_csrf(client)
    )
    assert res.status_code == 200

    async with sm() as s:
        user = (await s.scalars(select(User).where(User.email == "u@a.com"))).first()
        assert user is not None
        assert user.telegram_chat_id is None
