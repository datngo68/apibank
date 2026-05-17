from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import packages.db.session as session_module
from packages.config.settings import get_settings


@pytest.fixture
def reset_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    db_path = tmp_path / "apibank_test.sqlite"
    monkeypatch.setenv("APIBANK_DB_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("APIBANK_FERNET_KEYS", "")
    monkeypatch.setenv("APIBANK_API_KEY_SALT", "test-salt")
    monkeypatch.setenv("APIBANK_LOG_LEVEL", "WARNING")
    get_settings.cache_clear()
    session_module._engine = None
    session_module._sessionmaker = None
    yield
    session_module._engine = None
    session_module._sessionmaker = None
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_auth_rate_limit() -> Iterator[None]:
    """Tránh limiter in-memory rò state giữa các test (singleton process-wide)."""
    try:
        from apps.api.routes import auth as auth_module
        from packages.security.rate_limit import InMemoryRateLimiter

        auth_module._auth_email_limiter = InMemoryRateLimiter(
            capacity=auth_module._AUTH_RL_CAPACITY, window_seconds=60
        )
    except Exception:  # noqa: BLE001
        pass
    yield


@pytest.fixture
async def initialized_db(reset_settings: None) -> AsyncIterator[AsyncSession]:
    from packages.db.models import Base

    engine = session_module.get_engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessionmaker = session_module.get_sessionmaker()
    async with sessionmaker() as session:
        yield session
    await engine.dispose()


def pytest_collection_modifyitems(config, items) -> None:  # type: ignore[no-untyped-def]
    _ = config
    _ = asyncio
    _ = items
