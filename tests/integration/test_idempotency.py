from datetime import UTC, datetime

from fastapi.testclient import TestClient

from apps.api.main import create_app
from packages.config.settings import get_settings
from packages.db.models import BankAccount
from packages.security.bootstrap import create_api_key


async def test_idempotency_key_returns_same_response(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "idem_test.sqlite"
    monkeypatch.setenv("APIBANK_DB_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("APIBANK_FERNET_KEYS", "")
    monkeypatch.setenv("APIBANK_API_KEY_SALT", "test-salt")
    get_settings.cache_clear()

    import packages.db.session as session_module

    session_module._engine = None
    session_module._sessionmaker = None

    from packages.db.models import Base

    sessionmaker = session_module.get_sessionmaker()
    async with session_module.get_engine().begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    raw_key = ""
    bank_account_id = ""
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
        raw_key, _ = await create_api_key(session, scopes=["orders:write"])
        await session.commit()
        bank_account_id = bank_account.id

    app = create_app()
    payload = {"amount_vnd": 200000, "bank_account_id": bank_account_id, "ttl_seconds": 300}
    headers = {"Authorization": f"Bearer {raw_key}", "Idempotency-Key": "same-key"}
    with TestClient(app) as client:
        first = client.post("/v1/orders", json=payload, headers=headers)
        second = client.post("/v1/orders", json=payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    with TestClient(app) as client:
        conflict = client.post(
            "/v1/orders",
            json={**payload, "amount_vnd": 999999},
            headers=headers,
        )
    assert conflict.status_code == 409

    session_module._engine = None
    session_module._sessionmaker = None
    get_settings.cache_clear()
