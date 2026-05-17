from datetime import UTC, datetime
from decimal import Decimal

import httpx

from packages.banks.base import BankTransaction
from packages.config.settings import get_settings
from packages.core.ingest import ingest_transaction
from packages.db.models import BankAccount, Webhook
from packages.security.bootstrap import create_api_key
from packages.security.crypto import FernetCipher
from packages.webhook.dispatcher import dispatch_due_attempts


async def test_full_flow_order_to_webhook(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "e2e.sqlite"
    monkeypatch.setenv("APIBANK_DB_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("APIBANK_FERNET_KEYS", f"primary:{FernetCipher.generate_key()}")
    monkeypatch.setenv("APIBANK_API_KEY_SALT", "test-salt")
    get_settings.cache_clear()

    import packages.db.session as session_module

    session_module._engine = None
    session_module._sessionmaker = None

    from packages.db.models import Base, Order

    async with session_module.get_engine().begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    sessionmaker = session_module.get_sessionmaker()
    async with sessionmaker() as session:
        bank_account = BankAccount(
            id="ba_e2e",
            bank_code="MB",
            account_no="111",
            account_holder="T",
            credentials_enc="enc",
            status="active",
            polling_enabled=True,
            created_at=datetime.now(UTC),
        )
        webhook = Webhook(
            id="wh_e2e",
            owner_id="default",
            url="https://merchant.test/hook",
            secret_enc="topsecret",
            active=True,
            headers_json={},
            created_at=datetime.now(UTC),
        )
        order = Order.new(
            amount_vnd=Decimal("250000"), bank_account_id="ba_e2e", ttl_seconds=900
        )
        session.add_all([bank_account, webhook, order])
        await session.commit()
        await session.refresh(order)
        order_code = order.code

        await create_api_key(session, scopes=["orders:write"])
        await session.commit()

    bank_tx = BankTransaction(
        bank_ref_no="FT_E2E_1",
        posted_at=datetime.now(UTC),
        amount=Decimal("250000"),
        content=f"NAP TIEN {order_code}",
        counter_account=None,
        counter_name=None,
        raw={},
    )
    async with sessionmaker() as session:
        await ingest_transaction(session, bank_account_id="ba_e2e", bank_transaction=bank_tx)

    received = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(
            {
                "url": str(request.url),
                "headers": dict(request.headers),
                "body": request.content,
            }
        )
        return httpx.Response(200, text="ok")

    transport = httpx.MockTransport(handler)
    async with sessionmaker() as session, httpx.AsyncClient(transport=transport) as client:
        delivered = await dispatch_due_attempts(session, client=client)

    assert delivered == 1
    assert len(received) == 1
    sent = received[0]
    assert "x-signature" in sent["headers"]
    assert order_code.encode() in sent["body"]

    session_module._engine = None
    session_module._sessionmaker = None
    get_settings.cache_clear()
