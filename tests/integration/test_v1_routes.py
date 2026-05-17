from datetime import UTC, datetime

from fastapi.testclient import TestClient

from apps.api.main import create_app
from packages.config.settings import get_settings
from packages.db.models import BankAccount
from packages.security.bootstrap import create_api_key
from packages.security.crypto import FernetCipher


async def _setup(monkeypatch, tmp_path) -> tuple[str, str]:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "extra.sqlite"
    monkeypatch.setenv("APIBANK_DB_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("APIBANK_FERNET_KEYS", f"primary:{FernetCipher.generate_key()}")
    monkeypatch.setenv("APIBANK_API_KEY_SALT", "extra-salt")
    get_settings.cache_clear()

    import packages.db.session as session_module

    session_module._engine = None
    session_module._sessionmaker = None
    from packages.db.models import Base

    async with session_module.get_engine().begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    sessionmaker = session_module.get_sessionmaker()
    raw = ""
    bank_id = ""
    async with sessionmaker() as session:
        bank = BankAccount(
            id="ba_extra2",
            bank_code="MB",
            account_no="0000001",
            account_holder="X",
            credentials_enc="enc",
            status="active",
            polling_enabled=True,
            created_at=datetime.now(UTC),
        )
        session.add(bank)
        raw, _ = await create_api_key(
            session,
            scopes=[
                "orders:write",
                "orders:read",
                "transactions:read",
                "admin:*",
            ],
        )
        await session.commit()
        bank_id = bank.id
    return raw, bank_id


async def test_orders_lifecycle_get_and_cancel(monkeypatch, tmp_path) -> None:
    raw_key, bank_id = await _setup(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        created = client.post(
            "/v1/orders",
            json={"amount_vnd": 50000, "bank_account_id": bank_id, "ttl_seconds": 600},
            headers={
                "Authorization": f"Bearer {raw_key}",
                "Idempotency-Key": "lifecycle-1",
            },
        )
        assert created.status_code == 201
        order_id = created.json()["id"]

        fetched = client.get(
            f"/v1/orders/{order_id}",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert fetched.status_code == 200
        assert fetched.json()["status"] == "pending"

        canceled = client.post(
            f"/v1/orders/{order_id}:cancel",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert canceled.status_code == 200
        assert canceled.json()["status"] == "canceled"

    import packages.db.session as session_module

    session_module._engine = None
    session_module._sessionmaker = None
    get_settings.cache_clear()


async def test_transactions_endpoint_lists(monkeypatch, tmp_path) -> None:
    raw_key, bank_id = await _setup(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        response = client.get(
            "/v1/transactions",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
    assert response.status_code == 200
    assert response.json() == []

    import packages.db.session as session_module

    session_module._engine = None
    session_module._sessionmaker = None
    get_settings.cache_clear()


async def test_webhooks_v1_create_and_list(monkeypatch, tmp_path) -> None:
    raw_key, _ = await _setup(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        created = client.post(
            "/v1/webhooks",
            json={
                "url": "https://example.com/hook",
                "secret": "topsecretvalue123",
                "active": True,
            },
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert created.status_code == 201
        listed = client.get(
            "/v1/webhooks",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert listed.status_code == 200
        assert len(listed.json()) == 1

    import packages.db.session as session_module

    session_module._engine = None
    session_module._sessionmaker = None
    get_settings.cache_clear()
