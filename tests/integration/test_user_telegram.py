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
async def test_link_chat_503_when_telegram_not_configured(
    client: httpx.AsyncClient,
) -> None:
    """Khi chưa có bot_token → endpoint trả 503.

    Lưu ý: chỉ cần ``bot_token`` là user link được — không phụ thuộc admin
    có toggle ``enabled`` hay không. Test cũ kiểm tra ``enabled=False`` đã
    sai semantic mới và bị xoá; thay bằng test này.
    """
    import packages.db.session as session_module
    from packages.config import runtime as runtime_module

    sm = session_module.get_sessionmaker()
    async with sm() as s:
        # Xoá hẳn token (preserve_empty_secrets=False) để mô phỏng "chưa cấu hình".
        await runtime_module.set_config(
            s,
            "telegram",
            {"enabled": False, "bot_token": None, "bot_username": ""},
            actor_id="seed",
            encrypt_fields=("bot_token",),
            preserve_empty_secrets=False,
        )
        await s.commit()
    runtime_module.invalidate()

    await _register_login(client)
    res = await client.post(
        "/api/v1/auth/profile/telegram/link-chat", headers=_csrf(client)
    )
    assert res.status_code == 503


@pytest.mark.asyncio
async def test_link_chat_works_when_token_set_but_enabled_false(
    client: httpx.AsyncClient,
) -> None:
    """Admin đã save token nhưng chưa bật Switch — user vẫn link được.

    Đây là root cause user báo "đã add token mà vẫn báo chưa có": code cũ
    yêu cầu ``cfg.get("enabled")``, nay chỉ cần ``configured``.
    """
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
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_admin_save_token_auto_enables(
    client: httpx.AsyncClient,
) -> None:
    """Admin save bot_token với enabled=False → BE auto-bật để tránh trap UX."""
    import packages.db.session as session_module
    from packages.config import runtime as runtime_module
    from packages.db.models import User
    from packages.notifications import telegram as tg_pkg
    from packages.security.passwords import hash_password

    # Tạo admin user
    sm = session_module.get_sessionmaker()
    async with sm() as s:
        admin = User(
            email="admin@a.com",
            password_hash=hash_password("Strong-Pass-1"),
            full_name="Admin",
            role="admin",
            status="active",
        )
        s.add(admin)
        # reset cấu hình về trống
        await runtime_module.set_config(
            s,
            "telegram",
            {"enabled": False, "bot_token": None, "bot_username": ""},
            actor_id="seed",
            encrypt_fields=("bot_token",),
            preserve_empty_secrets=False,
        )
        await s.commit()
    runtime_module.invalidate()

    # Login admin
    await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@a.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )

    # Patch get_me để không gọi Telegram API thật
    async def _fake_get_me(token: str):  # type: ignore[no-untyped-def]
        return {"ok": True, "result": {"username": "apibank_test_bot"}}

    real_get_me = tg_pkg.get_me
    tg_pkg.get_me = _fake_get_me  # type: ignore[assignment]
    try:
        # Admin save token với enabled=False
        res = await client.put(
            "/api/v1/admin/config/telegram",
            json={"enabled": False, "bot_token": "987654:new-token"},
            headers=_csrf(client),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        # BE auto-bật vì có token mới
        assert body["enabled"] is True
        assert body["bot_token_set"] is True
    finally:
        tg_pkg.get_me = real_get_me  # type: ignore[assignment]

    # Verify resolver thấy token đã set
    async with sm() as s:
        cfg = await tg_pkg.resolve_telegram(s)
        assert cfg["configured"] is True
        assert cfg["enabled"] is True
        assert cfg["token"] == "987654:new-token"  # noqa: S105
        assert cfg["source"] == "app_config"


@pytest.mark.asyncio
async def test_link_chat_503_when_telegram_disabled(
    client: httpx.AsyncClient,
) -> None:
    """Backward-compat alias của test cũ — giờ trỏ vào case "chưa configured"."""
    import packages.db.session as session_module
    from packages.config import runtime as runtime_module

    sm = session_module.get_sessionmaker()
    async with sm() as s:
        await runtime_module.set_config(
            s,
            "telegram",
            {"enabled": False, "bot_token": None},
            actor_id="seed",
            encrypt_fields=("bot_token",),
            preserve_empty_secrets=False,
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
