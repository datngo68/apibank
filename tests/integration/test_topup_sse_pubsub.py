"""Phase 5: SSE topup nhận event qua Redis pub/sub.

Mock pub/sub bằng cách patch ``packages.infra_pubsub.subscribe``/
``wait_for_message`` để giả lập 1 message đến trong < 500ms.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest


@pytest.fixture
def app_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db_path = tmp_path / "sse.db"
    monkeypatch.setenv("APIBANK_DB_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("APIBANK_FERNET_KEYS", "")
    monkeypatch.setenv("APIBANK_API_KEY_SALT", "test-salt")
    monkeypatch.setenv("APIBANK_LOG_LEVEL", "WARNING")


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
        await ac.get("/healthz")
        yield ac
    await engine.dispose()
    session_module._engine = None
    session_module._sessionmaker = None


def _csrf(c: httpx.AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": c.cookies.get("apibank_csrf", "")}


async def _setup_user_and_topup(client: httpx.AsyncClient) -> tuple[str, str, str]:
    """Đăng ký user, system bank, và 1 topup pending. Trả ``(user_id, code, order_id)``."""
    import packages.db.session as session_module
    from packages.db.models import BankAccount, Order, User

    sm = session_module.get_sessionmaker()
    async with sm() as s:
        bank = BankAccount(
            bank_code="MB",
            account_no="00112233",
            account_holder="APIBANK",
            credentials_enc="x",
            status="active",
            polling_enabled=True,
            is_system_account=True,
        )
        s.add(bank)
        await s.flush()
        bank_id = bank.id
        await s.commit()

    await client.post(
        "/api/v1/auth/register",
        json={"email": "sse@e.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": "sse@e.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )

    async with sm() as s:
        from sqlalchemy import select

        user = (await s.scalars(select(User).where(User.email == "sse@e.com"))).first()
        assert user is not None
        order = Order.new(
            amount_vnd=Decimal(100_000),
            bank_account_id=bank_id,
            ttl_seconds=900,
            customer_ref=user.email,
            metadata_json={"kind": "topup", "user_id": user.id},
            user_id=user.id,
        )
        s.add(order)
        await s.flush()
        await s.commit()
        return user.id, order.code, order.id


@pytest.mark.asyncio
async def test_sse_emits_paid_via_pubsub(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Khi pub/sub nhận message, SSE emit event 'paid' trong < 1.5s."""
    user_id, code, order_id = await _setup_user_and_topup(client)

    incoming_messages: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    @asynccontextmanager
    async def fake_subscribe(channel: str) -> AsyncIterator[Any]:
        # Channel format: ``topup:paid:{order_id}``.
        assert channel == f"topup:paid:{order_id}", channel

        class _Stub:
            channel_name = channel

        yield _Stub()

    async def fake_wait(pubsub: Any, *, timeout: float) -> dict[str, Any] | None:
        if pubsub is None:
            await asyncio.sleep(timeout)
            return None
        try:
            return await asyncio.wait_for(incoming_messages.get(), timeout=timeout)
        except TimeoutError:
            return None

    monkeypatch.setattr(
        "apps.api.routes.topup_stream.subscribe", fake_subscribe
    )
    monkeypatch.setattr(
        "apps.api.routes.topup_stream.wait_for_message", fake_wait
    )

    async def trigger_paid_after_delay() -> None:
        await asyncio.sleep(0.2)
        # Cập nhật DB như ingest sẽ làm.
        import packages.db.session as session_module
        from packages.db.models import Order

        sm = session_module.get_sessionmaker()
        async with sm() as s:
            from sqlalchemy import select

            order = (
                await s.scalars(select(Order).where(Order.code == code))
            ).first()
            assert order is not None
            order.status = "paid"
            order.paid_at = datetime.now(UTC)
            order.updated_at = datetime.now(UTC)
            await s.commit()
        # Push message qua pub/sub fake.
        await incoming_messages.put(
            {"type": "message", "data": json.dumps({"order_id": "x"})}
        )

    start = datetime.now(UTC)
    trigger = asyncio.create_task(trigger_paid_after_delay())

    received_paid = False
    elapsed = timedelta()
    async with client.stream(
        "GET", f"/api/v1/me/topup/{code}/events", timeout=10.0
    ) as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            if "event: paid" in line:
                received_paid = True
                elapsed = datetime.now(UTC) - start
                break
            if "event: timeout" in line:
                break

    await trigger
    assert received_paid, "phải nhận event paid qua pub/sub"
    assert elapsed.total_seconds() < 1.5, (
        f"latency {elapsed.total_seconds()}s vượt ngưỡng 1.5s"
    )
