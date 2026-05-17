"""Integration test cho /api/v1/me/notification-preferences.

- GET trả full matrix mặc định (merge từ DEFAULT_CHANNELS).
- PUT bulk upsert override channel cho từng kind.
- Validate kind/channel không hợp lệ trả 400.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest


@pytest.fixture
def app_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    db_path = tmp_path / "noti_pref.db"
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


async def _register_login(client: httpx.AsyncClient, email: str) -> None:
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
async def test_get_returns_full_matrix(client: httpx.AsyncClient) -> None:
    """Khi DB chưa có override, GET trả toàn bộ kind x channel với enabled = default."""
    from packages.notifications.dispatcher import DEFAULT_CHANNELS

    await _register_login(client, "pref1@e.com")
    res = await client.get("/api/v1/me/notification-preferences")
    assert res.status_code == 200
    items = res.json()["items"]

    expected_total = len(DEFAULT_CHANNELS) * 3  # 3 channels: in_app, email, telegram
    assert len(items) == expected_total

    # Spot-check: topup_credited mặc định bật cả 3 channels.
    topup = {i["channel"]: i["enabled"] for i in items if i["kind"] == "topup_credited"}
    assert topup == {"in_app": True, "email": True, "telegram": True}

    # subscription_purchased default bật in_app + email, tắt telegram.
    sub = {
        i["channel"]: i["enabled"]
        for i in items
        if i["kind"] == "subscription_purchased"
    }
    assert sub == {"in_app": True, "email": True, "telegram": False}


@pytest.mark.asyncio
async def test_put_overrides_persist(client: httpx.AsyncClient) -> None:
    """PUT bulk upsert ghi đè default. GET sau đó trả giá trị mới."""
    await _register_login(client, "pref2@e.com")

    payload = {
        "items": [
            {"kind": "topup_credited", "channel": "telegram", "enabled": False},
            {"kind": "webhook_failing", "channel": "email", "enabled": True},
        ]
    }
    res = await client.put(
        "/api/v1/me/notification-preferences",
        json=payload,
        headers=_csrf(client),
    )
    assert res.status_code == 200

    items = res.json()["items"]
    by_key = {(i["kind"], i["channel"]): i["enabled"] for i in items}
    assert by_key[("topup_credited", "telegram")] is False
    # Channel chưa override giữ nguyên default.
    assert by_key[("topup_credited", "in_app")] is True
    assert by_key[("webhook_failing", "email")] is True

    # GET lại đảm bảo persist.
    res2 = await client.get("/api/v1/me/notification-preferences")
    by_key2 = {
        (i["kind"], i["channel"]): i["enabled"] for i in res2.json()["items"]
    }
    assert by_key2[("topup_credited", "telegram")] is False
    assert by_key2[("webhook_failing", "email")] is True


@pytest.mark.asyncio
async def test_put_invalid_kind_returns_400(client: httpx.AsyncClient) -> None:
    await _register_login(client, "pref3@e.com")
    res = await client.put(
        "/api/v1/me/notification-preferences",
        json={
            "items": [
                {"kind": "not_a_real_kind", "channel": "email", "enabled": True}
            ]
        },
        headers=_csrf(client),
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_put_invalid_channel_returns_400(client: httpx.AsyncClient) -> None:
    await _register_login(client, "pref4@e.com")
    res = await client.put(
        "/api/v1/me/notification-preferences",
        json={
            "items": [
                {"kind": "topup_credited", "channel": "sms", "enabled": True}
            ]
        },
        headers=_csrf(client),
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_put_requires_auth(client: httpx.AsyncClient) -> None:
    # CSRF middleware chạy trước auth → trả 403 nếu không có CSRF token,
    # 401 nếu có CSRF token nhưng chưa đăng nhập. Cả hai đều block unauth.
    res = await client.put(
        "/api/v1/me/notification-preferences",
        json={"items": []},
        headers=_csrf(client),
    )
    assert res.status_code == 401
