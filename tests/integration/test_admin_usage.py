"""Tests cho admin usage analytics endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest


@pytest.fixture
def app_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    db_path = tmp_path / "admin_usage.db"
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


def _csrf(c: httpx.AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": c.cookies.get("apibank_csrf", "")}


async def _register_admin(client: httpx.AsyncClient) -> None:
    from sqlalchemy import select

    import packages.db.session as session_module
    from packages.db.models import User

    await client.post(
        "/api/v1/auth/register",
        json={"email": "admin@a.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    sm = session_module.get_sessionmaker()
    async with sm() as s:
        user = (
            await s.scalars(select(User).where(User.email == "admin@a.com"))
        ).first()
        assert user is not None
        user.role = "admin"
        await s.commit()
    await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@a.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )


async def _seed_usage(*, user_id: str, api_key_id: str) -> None:
    """Seed dữ liệu api_usage_daily 5 ngày gần đây."""
    import packages.db.session as session_module
    from packages.db.models import ApiUsageDaily

    sm = session_module.get_sessionmaker()
    today = datetime.now(UTC).date()
    async with sm() as s:
        for i in range(5):
            day = today - timedelta(days=i)
            s.add(
                ApiUsageDaily(
                    day=day,
                    user_id=user_id,
                    api_key_id=api_key_id,
                    endpoint_group="orders.create",
                    count=10 + i,
                    error_count=i,
                    updated_at=datetime.now(UTC),
                )
            )
            s.add(
                ApiUsageDaily(
                    day=day,
                    user_id=user_id,
                    api_key_id=api_key_id,
                    endpoint_group="transactions.list",
                    count=5,
                    error_count=0,
                    updated_at=datetime.now(UTC),
                )
            )
        await s.commit()


@pytest.mark.asyncio
async def test_admin_usage_summary_and_timeseries(client: httpx.AsyncClient) -> None:
    from sqlalchemy import select

    import packages.db.session as session_module
    from packages.db.models import User

    await _register_admin(client)
    sm = session_module.get_sessionmaker()
    async with sm() as s:
        admin = (
            await s.scalars(select(User).where(User.email == "admin@a.com"))
        ).first()
        assert admin is not None
    await _seed_usage(user_id=admin.id, api_key_id="ak_seed")

    summary = await client.get("/api/v1/admin/usage/summary", params={"days": 7})
    assert summary.status_code == 200, summary.text
    body = summary.json()
    # 5 ngày × (10+...+14 + 5×5) = 60 + 25 = 85
    assert body["total_count"] == 85
    assert body["total_errors"] == 0 + 1 + 2 + 3 + 4
    assert body["unique_users"] == 1
    assert any(
        e["endpoint_group"] == "orders.create" for e in body["top_endpoints"]
    )

    series = await client.get("/api/v1/admin/usage/timeseries", params={"days": 7})
    assert series.status_code == 200
    points = series.json()["points"]
    assert len(points) == 7
    assert sum(p["count"] for p in points) == 85


@pytest.mark.asyncio
async def test_admin_user_usage(client: httpx.AsyncClient) -> None:
    from sqlalchemy import select

    import packages.db.session as session_module
    from packages.db.models import User

    await _register_admin(client)
    sm = session_module.get_sessionmaker()
    async with sm() as s:
        admin = (
            await s.scalars(select(User).where(User.email == "admin@a.com"))
        ).first()
        assert admin is not None
    await _seed_usage(user_id=admin.id, api_key_id="ak_seed")

    res = await client.get(
        f"/api/v1/admin/users/{admin.id}/usage", params={"days": 7}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["user_id"] == admin.id
    assert body["total_count"] == 85
    assert any(b["endpoint_group"] == "orders.create" for b in body["by_endpoint"])
    assert any(b["api_key_id"] == "ak_seed" for b in body["by_api_key"])
