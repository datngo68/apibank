"""Integration tests cho /api/v1/me/* và /api/v1/plans."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest


@pytest.fixture
def app_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    db_path = tmp_path / "me.db"
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
    from packages.config.settings import get_settings

    get_settings.cache_clear()
    session_module._engine = None
    session_module._sessionmaker = None
    from packages.db.models import Base

    engine = session_module.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # seed plans + system bank
    from packages.billing.plans_seed import seed_plans
    from packages.db.models import BankAccount

    sm = session_module.get_sessionmaker()
    async with sm() as s:
        await seed_plans(s)
        s.add(
            BankAccount(
                bank_code="MB",
                account_no="9999",
                account_holder="APIBANK SYSTEM",
                credentials_enc="x",
                status="active",
                polling_enabled=True,
                is_system_account=True,
            )
        )
        await s.commit()

    from apps.api.main import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        await ac.get("/healthz")  # warm csrf
        yield ac
    await engine.dispose()
    session_module._engine = None
    session_module._sessionmaker = None


def _csrf(client: httpx.AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("apibank_csrf", "")}


async def _register_login(client: httpx.AsyncClient, email: str = "u@a.com") -> None:
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
async def test_plans_public_endpoint(client: httpx.AsyncClient) -> None:
    res = await client.get("/api/v1/plans")
    assert res.status_code == 200
    plans = res.json()
    codes = {p["code"] for p in plans}
    assert {"trial-day", "monthly", "yearly"}.issubset(codes)


@pytest.mark.asyncio
async def test_me_unauthenticated_blocks_all_me_endpoints(client: httpx.AsyncClient) -> None:
    res = await client.get("/api/v1/me/wallet")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_create_list_delete_bank_account(client: httpx.AsyncClient) -> None:
    await _register_login(client)
    # create
    res = await client.post(
        "/api/v1/me/bank-accounts",
        json={
            "bank_code": "MB",
            "account_no": "111222",
            "account_holder": "Nguyen Van A",
            "username": "userA",
            "password": "passA",
        },
        headers=_csrf(client),
    )
    assert res.status_code == 201, res.text
    bank_id = res.json()["id"]
    # list
    items = await client.get("/api/v1/me/bank-accounts")
    assert items.status_code == 200
    assert any(b["id"] == bank_id for b in items.json())
    # delete
    delete = await client.delete(
        f"/api/v1/me/bank-accounts/{bank_id}", headers=_csrf(client)
    )
    assert delete.status_code == 200


@pytest.mark.asyncio
async def test_bank_account_isolation_between_users(client: httpx.AsyncClient) -> None:
    await _register_login(client, "a@a.com")
    res = await client.post(
        "/api/v1/me/bank-accounts",
        json={
            "bank_code": "MB",
            "account_no": "100100",
            "account_holder": "A",
            "username": "uname1",
            "password": "passone",
        },
        headers=_csrf(client),
    )
    assert res.status_code == 201, res.text
    other_bank = res.json()["id"]
    await client.post("/api/v1/auth/logout", headers=_csrf(client))
    await _register_login(client, "b@b.com")
    items = await client.get("/api/v1/me/bank-accounts")
    assert all(b["id"] != other_bank for b in items.json())
    delete = await client.delete(
        f"/api/v1/me/bank-accounts/{other_bank}", headers=_csrf(client)
    )
    assert delete.status_code == 404


@pytest.mark.asyncio
async def test_rotate_credentials(client: httpx.AsyncClient) -> None:
    await _register_login(client)
    res = await client.post(
        "/api/v1/me/bank-accounts",
        json={
            "bank_code": "MB",
            "account_no": "222333",
            "account_holder": "B",
            "username": "u1",
            "password": "p1",
        },
        headers=_csrf(client),
    )
    bank_id = res.json()["id"]
    res2 = await client.post(
        f"/api/v1/me/bank-accounts/{bank_id}/rotate",
        json={"username": "u2", "password": "p2"},
        headers=_csrf(client),
    )
    assert res2.status_code == 200


@pytest.mark.asyncio
async def test_create_list_delete_webhook(client: httpx.AsyncClient) -> None:
    await _register_login(client)
    res = await client.post(
        "/api/v1/me/webhooks",
        json={
            "name": "Shop A",
            "url": "https://example.com/hook",
            "secret": "s" * 32,
            "events": ["order.paid"],
        },
        headers=_csrf(client),
    )
    assert res.status_code == 201
    wh_id = res.json()["id"]
    items = await client.get("/api/v1/me/webhooks")
    assert any(w["id"] == wh_id for w in items.json())
    upd = await client.patch(
        f"/api/v1/me/webhooks/{wh_id}",
        json={"active": False, "ip_allowlist": "1.2.3.0/24"},
        headers=_csrf(client),
    )
    assert upd.status_code == 200 and upd.json()["active"] is False
    delete = await client.delete(f"/api/v1/me/webhooks/{wh_id}", headers=_csrf(client))
    assert delete.status_code == 200


@pytest.mark.asyncio
async def test_create_apikey_reveals_once(client: httpx.AsyncClient) -> None:
    await _register_login(client)
    res = await client.post(
        "/api/v1/me/api-keys",
        json={"name": "Default", "scopes": ["orders:write", "orders:read"]},
        headers=_csrf(client),
    )
    assert res.status_code == 201
    body = res.json()
    assert body["raw_key"].startswith("sk_live_")
    # list không trả raw_key
    items = await client.get("/api/v1/me/api-keys")
    assert items.status_code == 200
    assert all("raw_key" not in k for k in items.json())


@pytest.mark.asyncio
async def test_apikey_invalid_scope_400(client: httpx.AsyncClient) -> None:
    await _register_login(client)
    res = await client.post(
        "/api/v1/me/api-keys",
        json={"name": "X", "scopes": ["admin:*"]},
        headers=_csrf(client),
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_revoke_apikey(client: httpx.AsyncClient) -> None:
    await _register_login(client)
    res = await client.post(
        "/api/v1/me/api-keys",
        json={"name": "tmp"},
        headers=_csrf(client),
    )
    api_key_id = res.json()["id"]
    rev = await client.post(
        f"/api/v1/me/api-keys/{api_key_id}/revoke", headers=_csrf(client)
    )
    assert rev.status_code == 200


@pytest.mark.asyncio
async def test_topup_creates_order(client: httpx.AsyncClient) -> None:
    await _register_login(client)
    res = await client.post(
        "/api/v1/me/topup", json={"amount_vnd": 50_000}, headers=_csrf(client)
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["amount_vnd"] == "50000"
    assert body["pay_url"].endswith(f"/pay/{body['code']}")


@pytest.mark.asyncio
async def test_topup_amount_validation(client: httpx.AsyncClient) -> None:
    await _register_login(client)
    res = await client.post(
        "/api/v1/me/topup", json={"amount_vnd": 1_000}, headers=_csrf(client)
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_subscription_purchase_with_balance(client: httpx.AsyncClient) -> None:
    """Credit ví thẳng qua DB, sau đó mua plan trial-day (1k) qua API."""
    from sqlalchemy import select

    import packages.db.session as session_module
    from packages.billing import wallet as wallet_pkg
    from packages.db.models import User

    await _register_login(client)
    sm = session_module.get_sessionmaker()
    async with sm() as s:
        user = (await s.scalars(select(User).limit(1))).first()
        assert user is not None
        await wallet_pkg.credit(
            s, user_id=user.id, amount_vnd=10_000, idempotency_key="seed"
        )
        await s.commit()

    res = await client.post(
        "/api/v1/me/subscription/purchase",
        json={"plan_code": "trial-day"},
        headers=_csrf(client),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["plan_code"] == "trial-day"

    invoices = await client.get("/api/v1/me/invoices")
    assert invoices.status_code == 200
    assert len(invoices.json()) == 1


@pytest.mark.asyncio
async def test_subscription_insufficient_funds(client: httpx.AsyncClient) -> None:
    await _register_login(client)
    res = await client.post(
        "/api/v1/me/subscription/purchase",
        json={"plan_code": "monthly"},
        headers=_csrf(client),
    )
    assert res.status_code == 402


@pytest.mark.asyncio
async def test_orders_and_transactions_list(client: httpx.AsyncClient) -> None:
    await _register_login(client)
    # Tạo bank cho user, sau đó tạo order qua DB và list qua API
    create = await client.post(
        "/api/v1/me/bank-accounts",
        json={
            "bank_code": "MB",
            "account_no": "555555",
            "account_holder": "C",
            "username": "uone",
            "password": "ptwo",
        },
        headers=_csrf(client),
    )
    assert create.status_code == 201, create.text
    bank_id = create.json()["id"]

    import packages.db.session as session_module
    from packages.db.models import Order, Transaction

    sm = session_module.get_sessionmaker()
    async with sm() as s:
        s.add(
            Order.new(
                amount_vnd=Decimal(50_000),
                bank_account_id=bank_id,
                ttl_seconds=900,
            )
        )
        s.add(
            Transaction(
                bank_account_id=bank_id,
                bank_ref_no="REF1",
                amount_vnd=Decimal(50_000),
                content="DH123",
                posted_at=datetime.now(UTC),
                raw_json={},
                state="new",
            )
        )
        await s.commit()

    orders = await client.get("/api/v1/me/orders")
    assert orders.status_code == 200
    assert len(orders.json()) == 1
    txs = await client.get("/api/v1/me/transactions")
    assert txs.status_code == 200
    assert len(txs.json()) == 1


@pytest.mark.asyncio
async def test_wallet_balance_endpoint(client: httpx.AsyncClient) -> None:
    await _register_login(client)
    res = await client.get("/api/v1/me/wallet")
    assert res.status_code == 200
    assert Decimal(res.json()["balance_vnd"]) == Decimal(0)
