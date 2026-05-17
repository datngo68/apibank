"""IDOR/RBAC regression tests cho /v1/* endpoints (Bearer API key).

User A và User B mỗi người có 1 API key, 1 bank, 1 order, 1 transaction.
- A KHÔNG được đọc/cancel order của B → 404.
- A KHÔNG được liệt kê transaction theo bank của B → empty hoặc 404.
- API key admin scope `admin:*` thấy tất cả.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest


@pytest.fixture
def app_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    db_path = tmp_path / "idor.db"
    monkeypatch.setenv("APIBANK_DB_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("APIBANK_FERNET_KEYS", "")
    monkeypatch.setenv("APIBANK_API_KEY_SALT", "test-salt")
    monkeypatch.setenv("APIBANK_LOG_LEVEL", "WARNING")
    yield


@pytest.fixture
async def app_with_two_users(
    app_env: None,
) -> AsyncIterator[tuple[httpx.AsyncClient, dict[str, Any]]]:
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
        Order,
        Plan,
        Subscription,
        Transaction,
        User,
    )
    from packages.security.api_keys import generate_api_key, hash_api_key
    from packages.security.passwords import hash_password

    engine = session_module.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sm = session_module.get_sessionmaker()
    raw_a = generate_api_key()
    raw_b = generate_api_key()
    raw_admin = generate_api_key()
    ctx: dict[str, Any] = {}

    async with sm() as s:
        plan = Plan(
            code="month",
            name="Month",
            price_vnd=Decimal(15_000),
            duration_days=30,
            daily_quota=100,
            monthly_quota=0,
        )
        s.add(plan)
        await s.flush()

        for letter, raw in (("a", raw_a), ("b", raw_b)):
            user = User(
                email=f"{letter}@e.com",
                password_hash=hash_password("xxxxxxxx"),
                full_name=letter.upper(),
            )
            s.add(user)
            await s.flush()
            bank = BankAccount(
                user_id=user.id,
                bank_code="MB",
                account_no=f"{letter}1",
                account_holder=letter.upper(),
                credentials_enc="x",
                status="active",
                polling_enabled=True,
            )
            s.add(bank)
            await s.flush()
            order = Order.new(
                amount_vnd=Decimal(50_000),
                bank_account_id=bank.id,
                ttl_seconds=300,
            )
            s.add(order)
            tx = Transaction(
                bank_account_id=bank.id,
                bank_ref_no=f"ref-{letter}",
                amount_vnd=Decimal(10_000),
                content="ping",
                posted_at=datetime.now(UTC),
            )
            s.add(tx)
            s.add(
                Subscription(
                    user_id=user.id,
                    plan_id=plan.id,
                    started_at=datetime.now(UTC),
                    expires_at=datetime.now(UTC) + timedelta(days=30),
                    status="active",
                )
            )
            await s.flush()
            s.add(
                ApiKey(
                    owner_id=user.id,
                    user_id=user.id,
                    key_hash=hash_api_key(raw, salt="test-salt"),
                    scopes=["orders:read", "orders:write", "transactions:read"],
                )
            )
            ctx[letter] = {
                "user_id": user.id,
                "bank_id": bank.id,
                "order_id": order.id,
                "tx_id": tx.id,
                "api_key": raw,
            }

        # Admin key (không gắn user_id, scope admin:*)
        s.add(
            ApiKey(
                owner_id="default",
                key_hash=hash_api_key(raw_admin, salt="test-salt"),
                scopes=["admin:*"],
            )
        )
        ctx["admin_key"] = raw_admin
        await s.commit()

    from apps.api.main import create_app

    app_obj = create_app()
    transport = httpx.ASGITransport(app=app_obj)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.get("/healthz")
        yield client, ctx

    await engine.dispose()
    session_module._engine = None
    session_module._sessionmaker = None


def _bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


@pytest.mark.asyncio
async def test_get_order_idor_blocked(
    app_with_two_users: tuple[httpx.AsyncClient, dict[str, Any]],
) -> None:
    client, ctx = app_with_two_users
    # A đọc order của B → 404
    res = await client.get(
        f"/v1/orders/{ctx['b']['order_id']}",
        headers=_bearer(ctx["a"]["api_key"]),
    )
    assert res.status_code == 404, res.text
    # A đọc order của chính mình → 200
    own = await client.get(
        f"/v1/orders/{ctx['a']['order_id']}",
        headers=_bearer(ctx["a"]["api_key"]),
    )
    assert own.status_code == 200


@pytest.mark.asyncio
async def test_cancel_order_idor_blocked(
    app_with_two_users: tuple[httpx.AsyncClient, dict[str, Any]],
) -> None:
    client, ctx = app_with_two_users
    res = await client.post(
        f"/v1/orders/{ctx['b']['order_id']}:cancel",
        headers=_bearer(ctx["a"]["api_key"]),
    )
    assert res.status_code == 404

    own = await client.post(
        f"/v1/orders/{ctx['a']['order_id']}:cancel",
        headers=_bearer(ctx["a"]["api_key"]),
    )
    assert own.status_code == 200


@pytest.mark.asyncio
async def test_create_order_with_other_user_bank_blocked(
    app_with_two_users: tuple[httpx.AsyncClient, dict[str, Any]],
) -> None:
    """A tạo order vào bank của B → 404 (assert_bank_account_owned)."""
    client, ctx = app_with_two_users
    res = await client.post(
        "/v1/orders",
        json={"amount_vnd": 30_000, "bank_account_id": ctx["b"]["bank_id"]},
        headers={**_bearer(ctx["a"]["api_key"]), "Idempotency-Key": "x1"},
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_list_transactions_filtered_by_user(
    app_with_two_users: tuple[httpx.AsyncClient, dict[str, Any]],
) -> None:
    client, ctx = app_with_two_users
    res = await client.get("/v1/transactions", headers=_bearer(ctx["a"]["api_key"]))
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 1
    assert rows[0]["bank_account_id"] == ctx["a"]["bank_id"]


@pytest.mark.asyncio
async def test_list_transactions_other_account_filter_blocked(
    app_with_two_users: tuple[httpx.AsyncClient, dict[str, Any]],
) -> None:
    """A filter `account=<bank_b>` → 404 (assert_bank_account_owned)."""
    client, ctx = app_with_two_users
    res = await client.get(
        f"/v1/transactions?account={ctx['b']['bank_id']}",
        headers=_bearer(ctx["a"]["api_key"]),
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_admin_scope_can_access_any_order(
    app_with_two_users: tuple[httpx.AsyncClient, dict[str, Any]],
) -> None:
    client, ctx = app_with_two_users
    a = await client.get(f"/v1/orders/{ctx['a']['order_id']}", headers=_bearer(ctx["admin_key"]))
    b = await client.get(f"/v1/orders/{ctx['b']['order_id']}", headers=_bearer(ctx["admin_key"]))
    assert a.status_code == 200
    assert b.status_code == 200


@pytest.mark.asyncio
async def test_subscription_gate_applies_to_get_order(
    app_with_two_users: tuple[httpx.AsyncClient, dict[str, Any]],
) -> None:
    """Sub hết hạn → GET /v1/orders/{id} cũng phải 402, không chỉ POST."""
    import packages.db.session as session_module
    from packages.db.models import Subscription

    client, ctx = app_with_two_users
    sm = session_module.get_sessionmaker()
    async with sm() as s:
        from sqlalchemy import update

        await s.execute(
            update(Subscription)
            .where(Subscription.user_id == ctx["a"]["user_id"])
            .values(expires_at=datetime.now(UTC) - timedelta(days=1))
        )
        await s.commit()

    res = await client.get(
        f"/v1/orders/{ctx['a']['order_id']}",
        headers=_bearer(ctx["a"]["api_key"]),
    )
    assert res.status_code == 402, res.text


@pytest.mark.asyncio
async def test_subscription_gate_applies_to_list_transactions(
    app_with_two_users: tuple[httpx.AsyncClient, dict[str, Any]],
) -> None:
    import packages.db.session as session_module
    from packages.db.models import Subscription

    client, ctx = app_with_two_users
    sm = session_module.get_sessionmaker()
    async with sm() as s:
        from sqlalchemy import update

        await s.execute(
            update(Subscription)
            .where(Subscription.user_id == ctx["a"]["user_id"])
            .values(expires_at=datetime.now(UTC) - timedelta(days=1))
        )
        await s.commit()

    res = await client.get("/v1/transactions", headers=_bearer(ctx["a"]["api_key"]))
    assert res.status_code == 402
