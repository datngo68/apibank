"""Tests cho admin revenue endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest


@pytest.fixture
def app_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    db_path = tmp_path / "admin_revenue.db"
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


async def _register_admin(client: httpx.AsyncClient) -> str:
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
        admin_id = user.id
    await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@a.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    return admin_id


async def _seed_revenue(admin_id: str) -> None:
    """Seed plan + subscription + invoice + wallet topup/refund."""
    import packages.db.session as session_module
    from packages.db.models import (
        Invoice,
        Plan,
        Subscription,
        WalletTransaction,
    )

    sm = session_module.get_sessionmaker()
    now = datetime.now(UTC)
    async with sm() as s:
        plan = Plan(
            code="pro",
            name="Pro",
            description=None,
            price_vnd=Decimal(300_000),
            duration_days=30,
            daily_quota=1000,
            monthly_quota=30000,
            features_json={},
            sort_order=1,
            active=True,
        )
        s.add(plan)
        await s.flush()

        s.add(
            Subscription(
                user_id=admin_id,
                plan_id=plan.id,
                started_at=now,
                expires_at=now + timedelta(days=30),
                status="active",
                auto_renew=False,
            )
        )

        # 2 invoice paid trong 30 ngày qua
        s.add(
            Invoice(
                user_id=admin_id,
                plan_code="pro",
                amount_vnd=Decimal(300_000),
                currency="VND",
                status="paid",
                issued_at=now - timedelta(days=2),
                discount_vnd=Decimal(0),
            )
        )
        s.add(
            Invoice(
                user_id=admin_id,
                plan_code="pro",
                amount_vnd=Decimal(270_000),
                currency="VND",
                status="paid",
                issued_at=now - timedelta(days=10),
                coupon_code="SAVE10",
                discount_vnd=Decimal(30_000),
                original_amount_vnd=Decimal(300_000),
            )
        )

        # Topup ví
        s.add(
            WalletTransaction(
                user_id=admin_id,
                type="topup",
                amount_vnd=Decimal(100_000),
                balance_after=Decimal(100_000),
                idempotency_key="t1",
                created_at=now - timedelta(days=1),
            )
        )
        # Refund (negative amount)
        s.add(
            WalletTransaction(
                user_id=admin_id,
                type="refund",
                amount_vnd=Decimal(-20_000),
                balance_after=Decimal(80_000),
                idempotency_key="r1",
                created_at=now - timedelta(days=1),
            )
        )
        await s.commit()


@pytest.mark.asyncio
async def test_admin_revenue_summary(client: httpx.AsyncClient) -> None:
    admin_id = await _register_admin(client)
    await _seed_revenue(admin_id)

    res = await client.get("/api/v1/admin/revenue/summary")
    assert res.status_code == 200, res.text
    body = res.json()
    assert int(float(body["last_30d_vnd"])) == 570_000
    assert int(float(body["topup_vnd_30d"])) == 100_000
    assert int(float(body["refund_vnd_30d"])) == 20_000
    assert int(float(body["discount_vnd_30d"])) == 30_000
    assert body["total_invoices_paid"] == 2
    # MRR = 300_000 / 30 * 30 = 300_000
    assert int(float(body["mrr_vnd"])) == 300_000


@pytest.mark.asyncio
async def test_admin_revenue_by_plan_and_coupon(client: httpx.AsyncClient) -> None:
    admin_id = await _register_admin(client)
    await _seed_revenue(admin_id)

    by_plan = await client.get("/api/v1/admin/revenue/by-plan", params={"days": 30})
    assert by_plan.status_code == 200
    plans = by_plan.json()
    assert any(r["plan_code"] == "pro" and r["invoices"] == 2 for r in plans)

    by_coupon = await client.get(
        "/api/v1/admin/revenue/by-coupon", params={"days": 30}
    )
    assert by_coupon.status_code == 200
    coupons = by_coupon.json()
    assert any(
        r["coupon_code"] == "SAVE10" and int(float(r["discount_vnd"])) == 30_000
        for r in coupons
    )


@pytest.mark.asyncio
async def test_admin_invoices_listing(client: httpx.AsyncClient) -> None:
    admin_id = await _register_admin(client)
    await _seed_revenue(admin_id)

    res = await client.get(
        "/api/v1/admin/invoices",
        params={"status": "paid", "limit": 10},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 2
    assert all(item["status"] == "paid" for item in body["items"])


@pytest.mark.asyncio
async def test_admin_stats_includes_revenue(client: httpx.AsyncClient) -> None:
    admin_id = await _register_admin(client)
    await _seed_revenue(admin_id)

    res = await client.get("/api/v1/admin/stats")
    assert res.status_code == 200
    body = res.json()
    assert int(float(body["revenue_30d_vnd"])) == 570_000
    assert int(float(body["mrr_vnd"])) == 300_000
    assert "api_keys_active" in body
    assert "requests_24h" in body
