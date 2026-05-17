"""Integration tests cho /api/v1/admin/* + AppConfig runtime helper."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest


@pytest.fixture
def app_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    db_path = tmp_path / "admin.db"
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

    from packages.db.models import BankAccount, Base

    engine = session_module.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sm = session_module.get_sessionmaker()
    async with sm() as s:
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
        await ac.get("/healthz")
        yield ac
    await engine.dispose()
    session_module._engine = None
    session_module._sessionmaker = None


def _csrf(client: httpx.AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("apibank_csrf", "")}


async def _register_admin(client: httpx.AsyncClient, email: str = "admin@a.com") -> None:
    """Register + login + promote thành admin qua DB."""
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


async def _register_user(client: httpx.AsyncClient, email: str) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )


@pytest.mark.asyncio
async def test_admin_list_users_requires_admin(client: httpx.AsyncClient) -> None:
    await _register_user(client, "u@a.com")
    await client.post(
        "/api/v1/auth/login",
        json={"email": "u@a.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    res = await client.get("/api/v1/admin/users")
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_admin_full_user_flow(client: httpx.AsyncClient) -> None:
    await _register_admin(client)
    await _register_user(client, "x@a.com")

    listing = await client.get("/api/v1/admin/users")
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert body["total"] >= 2
    target = next(u for u in body["items"] if u["email"] == "x@a.com")

    # credit ví
    credit = await client.post(
        f"/api/v1/admin/users/{target['id']}/wallet/credit",
        json={"amount_vnd": 50_000, "note": "manual top-up"},
        headers=_csrf(client),
    )
    assert credit.status_code == 200, credit.text
    assert int(float(credit.json()["balance_after"])) == 50_000

    # adjust trừ tay
    adjust = await client.post(
        f"/api/v1/admin/users/{target['id']}/wallet/adjust",
        json={"amount_vnd": -10_000, "note": "fix"},
        headers=_csrf(client),
    )
    assert adjust.status_code == 200, adjust.text
    assert int(float(adjust.json()["balance_after"])) == 40_000

    # detail
    detail = await client.get(f"/api/v1/admin/users/{target['id']}")
    assert detail.status_code == 200
    assert int(float(detail.json()["balance_vnd"])) == 40_000

    # update role
    upd = await client.patch(
        f"/api/v1/admin/users/{target['id']}",
        json={"role": "admin"},
        headers=_csrf(client),
    )
    assert upd.status_code == 200
    assert upd.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_admin_plans_crud(client: httpx.AsyncClient) -> None:
    await _register_admin(client)
    res = await client.post(
        "/api/v1/admin/plans",
        json={
            "code": "test-plan",
            "name": "Test plan",
            "price_vnd": 10_000,
            "duration_days": 30,
            "daily_quota": 100,
            "monthly_quota": 1000,
        },
        headers=_csrf(client),
    )
    assert res.status_code == 201, res.text
    plan_id = res.json()["id"]

    upd = await client.patch(
        f"/api/v1/admin/plans/{plan_id}",
        json={"price_vnd": 20_000, "active": False},
        headers=_csrf(client),
    )
    assert upd.status_code == 200
    assert upd.json()["active"] is False
    assert int(float(upd.json()["price_vnd"])) == 20_000

    delete = await client.delete(
        f"/api/v1/admin/plans/{plan_id}", headers=_csrf(client)
    )
    assert delete.status_code == 200


@pytest.mark.asyncio
async def test_admin_system_bank_set_unset(client: httpx.AsyncClient) -> None:
    await _register_admin(client)
    listing = await client.get("/api/v1/admin/bank-accounts")
    assert listing.status_code == 200
    bank = listing.json()[0]
    bank_id = bank["id"]

    unset = await client.delete("/api/v1/admin/system-bank", headers=_csrf(client))
    assert unset.status_code == 200
    cur = await client.get("/api/v1/admin/system-bank")
    assert cur.status_code == 200
    assert cur.json() is None

    set_again = await client.post(
        "/api/v1/admin/system-bank",
        json={"bank_account_id": bank_id},
        headers=_csrf(client),
    )
    assert set_again.status_code == 200


@pytest.mark.asyncio
async def test_admin_smtp_config_roundtrip(client: httpx.AsyncClient) -> None:
    await _register_admin(client)
    body = {
        "host": "smtp.example.com",
        "port": 587,
        "user": "u",
        "password": "secret123",
        "from_addr": "x@example.com",
        "use_tls": True,
        "enabled": True,
    }
    res = await client.put("/api/v1/admin/config/smtp", json=body, headers=_csrf(client))
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["host"] == "smtp.example.com"
    assert data["password_set"] is True

    # Re-save với password rỗng → giữ nguyên
    body2 = {**body, "password": "", "host": "smtp2.example.com"}
    res2 = await client.put("/api/v1/admin/config/smtp", json=body2, headers=_csrf(client))
    assert res2.status_code == 200
    assert res2.json()["host"] == "smtp2.example.com"
    assert res2.json()["password_set"] is True


@pytest.mark.asyncio
async def test_admin_google_oauth_roundtrip(client: httpx.AsyncClient) -> None:
    await _register_admin(client)
    res = await client.put(
        "/api/v1/admin/config/google",
        json={
            "client_id": "abc.apps.googleusercontent.com",
            "client_secret": "GOCSPX-1",
            "redirect_uri": "https://x/callback",
            "enabled": True,
        },
        headers=_csrf(client),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["client_id"] == "abc.apps.googleusercontent.com"
    assert body["client_secret_set"] is True

    status = await client.get("/api/v1/auth/google/status")
    assert status.status_code == 200
    assert status.json()["enabled"] is True


@pytest.mark.asyncio
async def test_admin_audit_log_lists_actions(client: httpx.AsyncClient) -> None:
    await _register_admin(client)
    await _register_user(client, "victim@a.com")
    # Tạo 1 audit
    listing = await client.get("/api/v1/admin/users")
    target = next(u for u in listing.json()["items"] if u["email"] == "victim@a.com")
    await client.post(
        f"/api/v1/admin/users/{target['id']}/wallet/credit",
        json={"amount_vnd": 1_000, "note": "x"},
        headers=_csrf(client),
    )
    audit = await client.get(
        "/api/v1/admin/audit-log", params={"action": "admin.wallet"}
    )
    assert audit.status_code == 200, audit.text
    assert audit.json()["total"] >= 1
