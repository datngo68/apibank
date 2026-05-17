"""Verify SPA mount: /api endpoints vẫn JSON, /dashboard trả index.html."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest


@pytest.fixture
def app_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    db_path = tmp_path / "spa.db"
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
        yield ac
    await engine.dispose()
    session_module._engine = None
    session_module._sessionmaker = None


@pytest.mark.asyncio
async def test_root_serves_html(client: httpx.AsyncClient) -> None:
    res = await client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")
    assert '<div id="root"' in res.text


@pytest.mark.asyncio
async def test_unknown_route_serves_spa(client: httpx.AsyncClient) -> None:
    res = await client.get("/dashboard/something-fake")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_api_endpoints_remain_json(client: httpx.AsyncClient) -> None:
    res = await client.get("/api/v1/plans")
    assert res.status_code == 200
    assert "application/json" in res.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_healthz_not_swallowed(client: httpx.AsyncClient) -> None:
    res = await client.get("/healthz")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_admin_path_redirects_to_spa(client: httpx.AsyncClient) -> None:
    """Jinja `/admin/*` đã bị gỡ — `/admin/login` rơi vào SPA fallback (200 HTML).

    SPA admin sống ở `/app/admin/*`; route `/admin/login` thuần phía client sẽ
    hiển thị "Không tìm thấy" hoặc tương đương, nhưng vẫn trả index.html.
    """
    res = await client.get("/admin/login")
    assert res.status_code == 200
    body = res.text
    assert '<div id="root"' in body


@pytest.mark.asyncio
async def test_assets_have_immutable_cache(client: httpx.AsyncClient) -> None:
    """Lấy bất kỳ file nào trong /assets/ và kiểm Cache-Control."""
    import re

    root = await client.get("/")
    match = re.search(r"/assets/(index-[\w-]+\.(?:js|css))", root.text)
    assert match, root.text
    res = await client.get(f"/assets/{match.group(1)}")
    assert res.status_code == 200
    cache = res.headers.get("Cache-Control", "")
    assert "immutable" in cache and "max-age=31536000" in cache
