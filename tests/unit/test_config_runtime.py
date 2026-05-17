"""Tests cho packages.config.runtime — encrypt, cache, public_view."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import packages.db.session as session_module
from packages.config import runtime as runtime_module
from packages.config.settings import get_settings


@pytest.fixture
async def db_with_fernet(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> AsyncIterator[AsyncSession]:
    db_path = tmp_path / "rt.sqlite"
    monkeypatch.setenv("APIBANK_DB_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv(
        "APIBANK_FERNET_KEYS",
        "primary:NhnFbDTpYks-q2AmJsBhuG_iL6VDaKL14L4vy44ZqkM=",
    )
    monkeypatch.setenv("APIBANK_API_KEY_SALT", "test-salt")
    monkeypatch.setenv("APIBANK_LOG_LEVEL", "WARNING")
    get_settings.cache_clear()
    session_module._engine = None
    session_module._sessionmaker = None
    runtime_module.invalidate()

    from packages.db.models import Base

    engine = session_module.get_engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sm = session_module.get_sessionmaker()
    async with sm() as session:
        yield session
    await engine.dispose()
    session_module._engine = None
    session_module._sessionmaker = None
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_set_and_get_decrypted_roundtrip(db_with_fernet: AsyncSession) -> None:
    await runtime_module.set_config(
        db_with_fernet,
        "smtp",
        {"host": "smtp.example.com", "user": "u", "password": "secret123"},
        actor_id="admin",
        encrypt_fields=("password",),
    )
    await db_with_fernet.commit()

    runtime_module.invalidate()
    decrypted = await runtime_module.get_decrypted(
        db_with_fernet, "smtp", encrypted_fields=("password",)
    )
    assert decrypted["host"] == "smtp.example.com"
    assert decrypted["password"] == "secret123"  # noqa: S105


@pytest.mark.asyncio
async def test_empty_secret_preserves_existing(db_with_fernet: AsyncSession) -> None:
    await runtime_module.set_config(
        db_with_fernet,
        "smtp",
        {"host": "h", "password": "secret123"},
        actor_id="admin",
        encrypt_fields=("password",),
    )
    await db_with_fernet.commit()

    await runtime_module.set_config(
        db_with_fernet,
        "smtp",
        {"host": "h2", "password": ""},
        actor_id="admin",
        encrypt_fields=("password",),
    )
    await db_with_fernet.commit()

    runtime_module.invalidate()
    decrypted = await runtime_module.get_decrypted(
        db_with_fernet, "smtp", encrypted_fields=("password",)
    )
    assert decrypted["host"] == "h2"
    assert decrypted["password"] == "secret123"  # noqa: S105


@pytest.mark.asyncio
async def test_public_view_hides_secret_fields(db_with_fernet: AsyncSession) -> None:
    await runtime_module.set_config(
        db_with_fernet,
        "smtp",
        {"host": "h", "password": "secret"},
        actor_id="admin",
        encrypt_fields=("password",),
    )
    await db_with_fernet.commit()

    raw = await runtime_module.get_config(db_with_fernet, "smtp")
    pub = runtime_module.public_view(raw, encrypted_fields=("password",))
    assert pub["host"] == "h"
    assert pub["password_set"] is True
    assert "password_enc" not in pub
    assert "password" not in pub


@pytest.mark.asyncio
async def test_get_decrypted_uses_cache(db_with_fernet: AsyncSession) -> None:
    await runtime_module.set_config(
        db_with_fernet,
        "smtp",
        {"host": "first"},
        actor_id="admin",
    )
    await db_with_fernet.commit()

    a = await runtime_module.get_decrypted(db_with_fernet, "smtp")
    assert a["host"] == "first"

    from sqlalchemy import select

    from packages.db.models import AppConfig

    raw_row = (await db_with_fernet.execute(select(AppConfig))).scalars().first()
    assert raw_row is not None
    raw_row.value_json = {"host": "second"}
    await db_with_fernet.commit()

    b = await runtime_module.get_decrypted(db_with_fernet, "smtp")
    assert b["host"] == "first"  # vẫn cached

    runtime_module.invalidate("smtp")
    c = await runtime_module.get_decrypted(db_with_fernet, "smtp")
    assert c["host"] == "second"
