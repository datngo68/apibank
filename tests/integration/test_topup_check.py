"""Integration test cho POST /api/v1/me/topups/{order_id}:check.

Verify nút "Tôi đã chuyển khoản":
- Endpoint kick worker poll loop (set local event qua poll_kick).
- Trả ``paid`` + balance khi order đã được match (giả lập bằng cách ingest
  bank tx trong khi BE đang chờ).
- Trả ``pending`` + message hướng dẫn nếu hết timeout vẫn chưa match.
- Bảo vệ owner-only (404 cho user khác).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest


@pytest.fixture
def app_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    db_path = tmp_path / "topup_check.db"
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
        await ac.get("/healthz")  # warm csrf cookie
        yield ac
    await engine.dispose()
    session_module._engine = None
    session_module._sessionmaker = None


def _csrf(client: httpx.AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("apibank_csrf", "")}


async def _register_login(
    client: httpx.AsyncClient, email: str = "u@a.com"
) -> None:
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


async def _create_topup(client: httpx.AsyncClient, amount: int = 50_000) -> dict:
    res = await client.post(
        "/api/v1/me/topup",
        json={"amount_vnd": amount},
        headers=_csrf(client),
    )
    assert res.status_code == 201, res.text
    return res.json()


@pytest.mark.asyncio
async def test_check_pending_returns_pending_with_short_wait(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Không có tx khớp → trả ``pending`` sau timeout, không lỗi."""
    # Rút ngắn timeout để test chạy nhanh, không đợi 12s.
    from apps.api.routes import me as me_route

    monkeypatch.setattr(me_route, "_TOPUP_CHECK_MAX_WAIT_SEC", 0.2)
    monkeypatch.setattr(me_route, "_TOPUP_CHECK_POLL_SEC", 0.05)

    await _register_login(client)
    topup = await _create_topup(client)

    res = await client.post(
        f"/api/v1/me/topups/{topup['order_id']}:check",
        headers=_csrf(client),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "pending"
    assert body["balance_vnd"] is None
    assert "chưa thấy giao dịch" in body["message"].lower() or "chưa" in body["message"].lower()
    assert body["waited_ms"] >= 0


@pytest.mark.asyncio
async def test_check_returns_paid_when_tx_arrives_during_wait(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BE đang chờ → ingest tx khớp → BE phát hiện và trả ``paid``."""
    from apps.api.routes import me as me_route

    # Cho BE đợi đủ lâu để ingest task chen vào.
    monkeypatch.setattr(me_route, "_TOPUP_CHECK_MAX_WAIT_SEC", 5.0)
    monkeypatch.setattr(me_route, "_TOPUP_CHECK_POLL_SEC", 0.1)

    await _register_login(client)
    topup = await _create_topup(client, amount=80_000)

    # Spawn task ingest sau ~0.3s — mô phỏng worker poll thấy tx mới.
    async def _ingest_after_delay() -> None:
        await asyncio.sleep(0.3)
        from sqlalchemy import select

        import packages.db.session as session_module
        from packages.banks.base import BankTransaction
        from packages.core.ingest import ingest_transaction
        from packages.db.models import BankAccount

        sm = session_module.get_sessionmaker()
        async with sm() as s:
            bank = (
                await s.scalars(
                    select(BankAccount).where(BankAccount.is_system_account.is_(True))
                )
            ).first()
            assert bank is not None
            tx = BankTransaction(
                bank_ref_no="REF-CHECK",
                amount=Decimal(80_000),
                content=f"NAP TIEN {topup['code']}",
                posted_at=datetime.now(UTC),
                counter_account=None,
                counter_name=None,
                raw={"src": "test_check"},
            )
            await ingest_transaction(s, bank_account_id=bank.id, bank_transaction=tx)

    ingest_task = asyncio.create_task(_ingest_after_delay())

    res = await client.post(
        f"/api/v1/me/topups/{topup['order_id']}:check",
        headers=_csrf(client),
    )
    await ingest_task
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "paid", body
    assert Decimal(body["balance_vnd"]) == Decimal(80_000)
    assert body["waited_ms"] >= 200  # phải đợi tối thiểu vòng poll đầu tiên


@pytest.mark.asyncio
async def test_check_already_paid_returns_immediately(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Order đã ``paid`` từ trước → trả ngay, không sleep."""
    from apps.api.routes import me as me_route

    monkeypatch.setattr(me_route, "_TOPUP_CHECK_MAX_WAIT_SEC", 5.0)

    await _register_login(client)
    topup = await _create_topup(client, amount=20_000)

    # Ingest trước khi check → order chuyển paid sẵn.
    from sqlalchemy import select

    import packages.db.session as session_module
    from packages.banks.base import BankTransaction
    from packages.core.ingest import ingest_transaction
    from packages.db.models import BankAccount

    sm = session_module.get_sessionmaker()
    async with sm() as s:
        bank = (
            await s.scalars(
                select(BankAccount).where(BankAccount.is_system_account.is_(True))
            )
        ).first()
        assert bank is not None
        await ingest_transaction(
            s,
            bank_account_id=bank.id,
            bank_transaction=BankTransaction(
                bank_ref_no="REF-PRE-PAID",
                amount=Decimal(20_000),
                content=topup["code"],
                posted_at=datetime.now(UTC),
                counter_account=None,
                counter_name=None,
                raw={},
            ),
        )

    loop = asyncio.get_running_loop()
    started = loop.time()
    res = await client.post(
        f"/api/v1/me/topups/{topup['order_id']}:check",
        headers=_csrf(client),
    )
    elapsed = loop.time() - started

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "paid"
    assert body["waited_ms"] == 0
    assert elapsed < 2.0  # không spin tới 5s


@pytest.mark.asyncio
async def test_check_not_owner_returns_404(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """User khác cố check topup không phải của mình → 404 (không leak)."""
    from apps.api.routes import me as me_route

    monkeypatch.setattr(me_route, "_TOPUP_CHECK_MAX_WAIT_SEC", 0.2)
    monkeypatch.setattr(me_route, "_TOPUP_CHECK_POLL_SEC", 0.05)

    await _register_login(client, "owner@a.com")
    topup = await _create_topup(client)
    await client.post("/api/v1/auth/logout", headers=_csrf(client))

    await _register_login(client, "other@a.com")
    res = await client.post(
        f"/api/v1/me/topups/{topup['order_id']}:check",
        headers=_csrf(client),
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_check_unknown_order_returns_404(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.routes import me as me_route

    monkeypatch.setattr(me_route, "_TOPUP_CHECK_MAX_WAIT_SEC", 0.2)

    await _register_login(client)
    res = await client.post(
        "/api/v1/me/topups/ord_does_not_exist:check",
        headers=_csrf(client),
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_check_kicks_worker_poll_event(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Khi worker đang đăng ký event cho bank, gọi check phải set event đó."""
    from apps.api.routes import me as me_route
    from packages.banks import poll_kick

    monkeypatch.setattr(me_route, "_TOPUP_CHECK_MAX_WAIT_SEC", 0.2)
    monkeypatch.setattr(me_route, "_TOPUP_CHECK_POLL_SEC", 0.05)

    await _register_login(client)
    topup = await _create_topup(client)

    # Tìm system bank id để register event giả lập worker.
    from sqlalchemy import select

    import packages.db.session as session_module
    from packages.db.models import BankAccount

    sm = session_module.get_sessionmaker()
    async with sm() as s:
        bank = (
            await s.scalars(
                select(BankAccount).where(BankAccount.is_system_account.is_(True))
            )
        ).first()
        assert bank is not None
        bank_id = bank.id

    ev = poll_kick.register(bank_id)
    try:
        ev.clear()
        res = await client.post(
            f"/api/v1/me/topups/{topup['order_id']}:check",
            headers=_csrf(client),
        )
        assert res.status_code == 200
        # API đã gọi poll_kick.kick → local event phải được set.
        assert ev.is_set()
    finally:
        poll_kick.unregister(bank_id)
