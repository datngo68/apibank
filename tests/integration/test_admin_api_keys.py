"""Tests cho admin API key management + admin user_detail bao gồm api_keys."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest


@pytest.fixture
def app_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    db_path = tmp_path / "admin_keys.db"
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


async def _register_admin(client: httpx.AsyncClient, email: str = "admin@a.com") -> None:
    from sqlalchemy import select

    import packages.db.session as session_module
    from packages.db.models import User

    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    sm = session_module.get_sessionmaker()
    async with sm() as s:
        user = (await s.scalars(select(User).where(User.email == email))).first()
        assert user is not None
        user.role = "admin"
        await s.commit()
    await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )


async def _register_user(client: httpx.AsyncClient, email: str) -> str:
    """Đăng ký user và trả về user_id."""
    from sqlalchemy import select

    import packages.db.session as session_module
    from packages.db.models import User

    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    sm = session_module.get_sessionmaker()
    async with sm() as s:
        user = (await s.scalars(select(User).where(User.email == email))).first()
        assert user is not None
        return user.id


@pytest.mark.asyncio
async def test_admin_create_user_api_key_and_revoke(client: httpx.AsyncClient) -> None:
    await _register_admin(client)
    target_id = await _register_user(client, "client@a.com")

    create = await client.post(
        f"/api/v1/admin/users/{target_id}/api-keys",
        json={"name": "for-restore", "scopes": ["orders:read"]},
        headers=_csrf(client),
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["raw_key"].startswith("sk_")
    assert body["user_id"] == target_id
    key_id = body["id"]

    listing = await client.get(
        "/api/v1/admin/api-keys",
        params={"user_id": target_id},
    )
    assert listing.status_code == 200
    assert any(k["id"] == key_id for k in listing.json()["items"])

    user_keys = await client.get(f"/api/v1/admin/users/{target_id}/api-keys")
    assert user_keys.status_code == 200
    assert len(user_keys.json()) == 1

    revoke = await client.post(
        f"/api/v1/admin/api-keys/{key_id}/revoke",
        headers=_csrf(client),
    )
    assert revoke.status_code == 200

    listing2 = await client.get(
        "/api/v1/admin/api-keys",
        params={"user_id": target_id, "revoked": "true"},
    )
    assert listing2.status_code == 200
    assert any(k["id"] == key_id for k in listing2.json()["items"])


@pytest.mark.asyncio
async def test_admin_user_detail_includes_api_keys(client: httpx.AsyncClient) -> None:
    await _register_admin(client)
    target_id = await _register_user(client, "u2@a.com")

    await client.post(
        f"/api/v1/admin/users/{target_id}/api-keys",
        json={"name": "k1", "scopes": ["orders:read"]},
        headers=_csrf(client),
    )

    detail = await client.get(f"/api/v1/admin/users/{target_id}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["api_keys_count"] == 1
    assert len(body["recent_api_keys"]) == 1
    assert body["recent_api_keys"][0]["name"] == "k1"


@pytest.mark.asyncio
async def test_admin_create_api_key_rejects_invalid_scope(client: httpx.AsyncClient) -> None:
    await _register_admin(client)
    target_id = await _register_user(client, "u3@a.com")

    res = await client.post(
        f"/api/v1/admin/users/{target_id}/api-keys",
        json={"name": "bad", "scopes": ["super:hacker"]},
        headers=_csrf(client),
    )
    assert res.status_code == 400
