"""Test enforce_subscription_and_quota dependency.

Tạo user, api key gắn user, gọi endpoint /v1/orders trực tiếp với Bearer key.
- Không sub → 402
- Có sub → tạo được order
- Vượt quota → 429
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest


@pytest.fixture
def app_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    db_path = tmp_path / "subgate.db"
    monkeypatch.setenv("APIBANK_DB_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("APIBANK_FERNET_KEYS", "")
    monkeypatch.setenv("APIBANK_API_KEY_SALT", "test-salt")
    monkeypatch.setenv("APIBANK_LOG_LEVEL", "WARNING")
    yield


@pytest.fixture
async def app(app_env: None) -> AsyncIterator[tuple[httpx.AsyncClient, dict[str, str]]]:
    import packages.db.session as session_module
    from packages.config.settings import get_settings

    get_settings.cache_clear()
    session_module._engine = None
    session_module._sessionmaker = None
    from packages.billing.quota import reset_quota_singleton

    reset_quota_singleton()

    from packages.db.models import (
        ApiKey,
        BankAccount,
        Base,
        Plan,
        User,
    )
    from packages.security.api_keys import generate_api_key, hash_api_key
    from packages.security.passwords import hash_password

    engine = session_module.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sm = session_module.get_sessionmaker()
    async with sm() as s:
        user = User(email="o@a.com", password_hash=hash_password("xxxxxxxx"), full_name="O")
        s.add(user)
        await s.flush()
        bank = BankAccount(
            user_id=user.id,
            bank_code="MB",
            account_no="1",
            account_holder="A",
            credentials_enc="x",
            status="active",
            polling_enabled=True,
        )
        s.add(bank)
        plan = Plan(
            code="month",
            name="Month",
            price_vnd=Decimal(15_000),
            duration_days=30,
            daily_quota=2,
            monthly_quota=0,
        )
        s.add(plan)
        await s.flush()
        raw = generate_api_key()
        digest = hash_api_key(raw, salt="test-salt")
        ak = ApiKey(
            owner_id="default",
            user_id=user.id,
            key_hash=digest,
            scopes=["orders:write", "orders:read"],
        )
        s.add(ak)
        await s.commit()

    from apps.api.main import create_app

    app_obj = create_app()
    transport = httpx.ASGITransport(app=app_obj)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.get("/healthz")  # warm cookie
        ctx = {
            "user_id": user.id,
            "bank_id": bank.id,
            "api_key": raw,
            "plan_id": plan.id,
        }
        yield client, ctx

    await engine.dispose()
    session_module._engine = None
    session_module._sessionmaker = None


async def _activate_sub(user_id: str, plan_id: str) -> None:
    import packages.db.session as session_module
    from packages.db.models import Subscription

    sm = session_module.get_sessionmaker()
    async with sm() as s:
        sub = Subscription(
            user_id=user_id,
            plan_id=plan_id,
            started_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(days=30),
            status="active",
        )
        s.add(sub)
        await s.commit()


def _bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


@pytest.mark.asyncio
async def test_no_subscription_returns_402(app: tuple[httpx.AsyncClient, dict[str, str]]) -> None:
    client, ctx = app
    res = await client.post(
        "/v1/orders",
        json={"amount_vnd": 50_000, "bank_account_id": ctx["bank_id"]},
        headers={**_bearer(ctx["api_key"]), "Idempotency-Key": "k1"},
    )
    assert res.status_code == 402, res.text


@pytest.mark.asyncio
async def test_active_subscription_allows_order(
    app: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    client, ctx = app
    await _activate_sub(ctx["user_id"], ctx["plan_id"])
    res = await client.post(
        "/v1/orders",
        json={"amount_vnd": 50_000, "bank_account_id": ctx["bank_id"]},
        headers={**_bearer(ctx["api_key"]), "Idempotency-Key": "ok1"},
    )
    assert res.status_code == 201, res.text


@pytest.mark.asyncio
async def test_quota_exceeded_returns_429(
    app: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    client, ctx = app
    await _activate_sub(ctx["user_id"], ctx["plan_id"])
    # Plan có daily_quota=2 → request thứ 3 phải 429
    for i in range(2):
        r = await client.post(
            "/v1/orders",
            json={"amount_vnd": 10_000, "bank_account_id": ctx["bank_id"]},
            headers={**_bearer(ctx["api_key"]), "Idempotency-Key": f"q{i}"},
        )
        assert r.status_code == 201, r.text
    third = await client.post(
        "/v1/orders",
        json={"amount_vnd": 10_000, "bank_account_id": ctx["bank_id"]},
        headers={**_bearer(ctx["api_key"]), "Idempotency-Key": "q3"},
    )
    assert third.status_code == 429, third.text


@pytest.mark.asyncio
async def test_admin_key_bypasses_subscription(
    app: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    """API key có scope admin:* bypass subscription gate."""
    import packages.db.session as session_module
    from packages.db.models import ApiKey
    from packages.security.api_keys import generate_api_key, hash_api_key

    sm = session_module.get_sessionmaker()
    async with sm() as s:
        raw_admin = generate_api_key()
        s.add(
            ApiKey(
                owner_id="default",
                key_hash=hash_api_key(raw_admin, salt="test-salt"),
                scopes=["admin:*"],
            )
        )
        await s.commit()

    client, ctx = app
    res = await client.post(
        "/v1/orders",
        json={"amount_vnd": 30_000, "bank_account_id": ctx["bank_id"]},
        headers={**_bearer(raw_admin), "Idempotency-Key": "admin1"},
    )
    assert res.status_code == 201, res.text


@pytest.mark.asyncio
async def test_legacy_api_key_without_user_id_bypasses(
    app: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    """Key cũ không có user_id (single-tenant) vẫn dùng được, không bị gate."""
    import packages.db.session as session_module
    from packages.db.models import ApiKey
    from packages.security.api_keys import generate_api_key, hash_api_key

    sm = session_module.get_sessionmaker()
    async with sm() as s:
        raw_legacy = generate_api_key()
        s.add(
            ApiKey(
                owner_id="default",
                key_hash=hash_api_key(raw_legacy, salt="test-salt"),
                scopes=["orders:write"],
            )
        )
        await s.commit()

    client, ctx = app
    res = await client.post(
        "/v1/orders",
        json={"amount_vnd": 25_000, "bank_account_id": ctx["bank_id"]},
        headers={**_bearer(raw_legacy), "Idempotency-Key": "leg1"},
    )
    assert res.status_code == 201, res.text


@pytest.mark.asyncio
async def test_expired_subscription_returns_402(
    app: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    """Sub đã hết hạn → 402."""
    import packages.db.session as session_module
    from packages.db.models import Subscription

    client, ctx = app
    sm = session_module.get_sessionmaker()
    async with sm() as s:
        sub = Subscription(
            user_id=ctx["user_id"],
            plan_id=ctx["plan_id"],
            started_at=datetime.now(UTC) - timedelta(days=40),
            expires_at=datetime.now(UTC) - timedelta(days=1),
            status="active",
        )
        s.add(sub)
        await s.commit()
    res = await client.post(
        "/v1/orders",
        json={"amount_vnd": 30_000, "bank_account_id": ctx["bank_id"]},
        headers={**_bearer(ctx["api_key"]), "Idempotency-Key": "exp1"},
    )
    assert res.status_code == 402


@pytest.mark.asyncio
async def test_invalid_api_key_returns_401(
    app: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    client, ctx = app
    res = await client.post(
        "/v1/orders",
        json={"amount_vnd": 30_000, "bank_account_id": ctx["bank_id"]},
        headers={"Authorization": "Bearer sk_live_bogus", "Idempotency-Key": "bad"},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_missing_api_key_returns_401(
    app: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    client, ctx = app
    res = await client.post(
        "/v1/orders",
        json={"amount_vnd": 30_000, "bank_account_id": ctx["bank_id"]},
        headers={"Idempotency-Key": "miss"},
    )
    assert res.status_code == 401
