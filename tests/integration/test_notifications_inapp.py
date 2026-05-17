"""Integration test cho /api/v1/me/notifications inbox.

- Seed 1 in_app notification trực tiếp DB (qua `create_in_app`).
- GET /me/notifications trả nó.
- /unread-count trả 1 → mark read → 0.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest


@pytest.fixture
def app_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    db_path = tmp_path / "noti.db"
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


async def _seed_notification(email: str, *, kind: str = "topup_credited") -> str:
    """Tạo in-app notification cho user. Trả notification_id."""
    from sqlalchemy import select

    import packages.db.session as session_module
    from packages.db.models import User
    from packages.notifications.in_app import create_in_app

    sm = session_module.get_sessionmaker()
    async with sm() as s:
        user = (await s.scalars(select(User).where(User.email == email))).first()
        assert user is not None
        record = await create_in_app(
            s,
            user_id=user.id,
            kind=kind,
            title="Test noti",
            body="hello",
            payload={"foo": "bar"},
        )
        await s.commit()
        return record.id


@pytest.mark.asyncio
async def test_list_notifications_returns_seeded(client: httpx.AsyncClient) -> None:
    await _register_login(client, "noti1@e.com")
    await _seed_notification("noti1@e.com")
    res = await client.get("/api/v1/me/notifications")
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 1
    assert items[0]["title"] == "Test noti"
    assert items[0]["kind"] == "topup_credited"
    assert items[0]["read_at"] is None


@pytest.mark.asyncio
async def test_unread_count_and_mark_read(client: httpx.AsyncClient) -> None:
    await _register_login(client, "noti2@e.com")
    nid = await _seed_notification("noti2@e.com")

    cnt = await client.get("/api/v1/me/notifications/unread-count")
    assert cnt.status_code == 200
    assert cnt.json()["unread"] == 1

    mark = await client.patch(f"/api/v1/me/notifications/{nid}", headers=_csrf(client))
    assert mark.status_code == 200
    assert mark.json()["read_at"] is not None

    cnt2 = await client.get("/api/v1/me/notifications/unread-count")
    assert cnt2.json()["unread"] == 0


@pytest.mark.asyncio
async def test_read_all(client: httpx.AsyncClient) -> None:
    await _register_login(client, "noti3@e.com")
    for _ in range(3):
        await _seed_notification("noti3@e.com")

    cnt = await client.get("/api/v1/me/notifications/unread-count")
    assert cnt.json()["unread"] == 3

    res = await client.post(
        "/api/v1/me/notifications/read-all", headers=_csrf(client)
    )
    assert res.status_code == 200

    cnt2 = await client.get("/api/v1/me/notifications/unread-count")
    assert cnt2.json()["unread"] == 0


@pytest.mark.asyncio
async def test_unread_only_filter(client: httpx.AsyncClient) -> None:
    await _register_login(client, "noti4@e.com")
    nid_a = await _seed_notification("noti4@e.com", kind="topup_credited")
    await _seed_notification("noti4@e.com", kind="subscription_purchased")

    # mark nid_a read
    await client.patch(f"/api/v1/me/notifications/{nid_a}", headers=_csrf(client))

    res = await client.get("/api/v1/me/notifications?unread_only=true")
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 1
    assert items[0]["kind"] == "subscription_purchased"


@pytest.mark.asyncio
async def test_mark_other_user_notification_returns_404(
    client: httpx.AsyncClient,
) -> None:
    await _register_login(client, "owner@e.com")
    other_nid = await _seed_notification("owner@e.com")

    # logout, register/login user khác
    await client.post("/api/v1/auth/logout", headers=_csrf(client))
    await _register_login(client, "intruder@e.com")

    res = await client.patch(
        f"/api/v1/me/notifications/{other_nid}", headers=_csrf(client)
    )
    assert res.status_code == 404
