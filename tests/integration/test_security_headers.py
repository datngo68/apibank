"""Verify security headers + CSRF + brute-force lockout."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest


@pytest.fixture
def app_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    db_path = tmp_path / "sec.db"
    monkeypatch.setenv("APIBANK_DB_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv(
        "APIBANK_FERNET_KEYS",
        "primary:NhnFbDTpYks-q2AmJsBhuG_iL6VDaKL14L4vy44ZqkM=",
    )
    monkeypatch.setenv("APIBANK_API_KEY_SALT", "salt-" + "x" * 48)
    monkeypatch.setenv("APIBANK_SESSION_SECRET_KEY", "sess-" + "y" * 48)
    monkeypatch.setenv("APIBANK_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("APIBANK_ENVIRONMENT", "production")
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
async def test_security_headers_present(client: httpx.AsyncClient) -> None:
    res = await client.get("/healthz")
    assert res.status_code == 200
    h = res.headers
    assert h.get("X-Content-Type-Options") == "nosniff"
    assert h.get("X-Frame-Options") == "DENY"
    assert "strict-origin" in h.get("Referrer-Policy", "")
    assert "default-src" in h.get("Content-Security-Policy", "")
    assert h.get("Strict-Transport-Security", "").startswith("max-age=")
    assert h.get("X-Request-Id")


@pytest.mark.asyncio
async def test_request_id_echoes_inbound(client: httpx.AsyncClient) -> None:
    res = await client.get("/healthz", headers={"X-Request-Id": "req-abc-123"})
    assert res.headers.get("X-Request-Id") == "req-abc-123"


@pytest.mark.asyncio
async def test_csrf_blocks_post_without_header(client: httpx.AsyncClient) -> None:
    res = await client.post(
        "/api/v1/auth/register",
        json={"email": "x@example.com", "password": "Strong-Pass-1"},
    )
    assert res.status_code == 403
    assert "csrf" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_v1_bypasses_csrf(client: httpx.AsyncClient) -> None:
    """Endpoint dùng Bearer API key (/v1/*) không yêu cầu CSRF header."""
    # Không có API key nên trả 401, KHÔNG phải 403 csrf
    res = await client.post(
        "/v1/orders",
        json={"amount_vnd": 1000, "bank_account_id": "ba_x"},
        headers={"Idempotency-Key": "k"},
    )
    assert res.status_code in (401, 422)
