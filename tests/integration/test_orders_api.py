from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from apps.api.main import create_app
from packages.config.settings import get_settings
from packages.db.models import BankAccount
from packages.db.session import get_sessionmaker
from packages.security.bootstrap import create_api_key


async def _bootstrap(monkeypatch_settings) -> tuple[str, str]:  # type: ignore[no-untyped-def]
    raw_key = ""
    bank_account_id = ""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        bank_account = BankAccount(
            bank_code="MB",
            account_no="123",
            account_holder="Tester",
            credentials_enc="enc",
            status="active",
            polling_enabled=True,
            created_at=datetime.now(UTC),
        )
        session.add(bank_account)
        raw_key, _ = await create_api_key(session, scopes=["orders:write", "orders:read"])
        await session.commit()
        bank_account_id = bank_account.id
    return raw_key, bank_account_id


async def test_create_order_persists_and_returns_201(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "api_test.sqlite"
    monkeypatch.setenv("APIBANK_DB_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("APIBANK_FERNET_KEYS", "")
    monkeypatch.setenv("APIBANK_API_KEY_SALT", "test-salt")
    get_settings.cache_clear()

    import packages.db.session as session_module

    session_module._engine = None
    session_module._sessionmaker = None

    from packages.db.models import Base

    async with session_module.get_engine().begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    raw_key, bank_account_id = await _bootstrap(monkeypatch)

    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/v1/orders",
            json={
                "amount_vnd": 150000,
                "bank_account_id": bank_account_id,
                "ttl_seconds": 600,
            },
            headers={
                "Authorization": f"Bearer {raw_key}",
                "Idempotency-Key": "test-key-1",
            },
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "pending"
    assert Decimal(str(body["amount_vnd"])) == Decimal("150000")

    session_module._engine = None
    session_module._sessionmaker = None
    get_settings.cache_clear()
