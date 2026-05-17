from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from apps.api.main import create_app
from packages.config.settings import get_settings
from packages.db.models import BankAccount, Order
from packages.security.crypto import FernetCipher


async def _setup(monkeypatch, tmp_path) -> str:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "qr.sqlite"
    monkeypatch.setenv("APIBANK_DB_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("APIBANK_FERNET_KEYS", f"primary:{FernetCipher.generate_key()}")
    monkeypatch.setenv("APIBANK_API_KEY_SALT", "qr-salt")
    get_settings.cache_clear()

    import packages.db.session as session_module

    session_module._engine = None
    session_module._sessionmaker = None

    from packages.db.models import Base

    async with session_module.get_engine().begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    sessionmaker = session_module.get_sessionmaker()
    order_id = ""
    code = ""
    async with sessionmaker() as session:
        bank_account = BankAccount(
            id="ba_qr",
            bank_code="MB",
            account_no="1234567",
            account_holder="X",
            credentials_enc="enc",
            status="active",
            polling_enabled=True,
            created_at=datetime.now(UTC),
        )
        order = Order.new(
            amount_vnd=Decimal("50000"), bank_account_id="ba_qr", ttl_seconds=900
        )
        session.add_all([bank_account, order])
        await session.commit()
        await session.refresh(order)
        order_id = order.id
        code = order.code
    return f"{order_id}|{code}"


async def test_qr_png_endpoint_returns_png(monkeypatch, tmp_path) -> None:
    info = await _setup(monkeypatch, tmp_path)
    order_id, _ = info.split("|")
    app = create_app()
    with TestClient(app) as client:
        response = client.get(f"/qr/{order_id}.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"

    import packages.db.session as session_module

    session_module._engine = None
    session_module._sessionmaker = None
    get_settings.cache_clear()


async def test_payment_page_renders_html(monkeypatch, tmp_path) -> None:
    info = await _setup(monkeypatch, tmp_path)
    _, code = info.split("|")
    app = create_app()
    with TestClient(app) as client:
        page = client.get(f"/pay/{code}")
        status_resp = client.get(f"/pay/{code}/status")
    assert page.status_code == 200
    assert "Thanh toán đơn" in page.text
    assert "/qr/" in page.text
    assert status_resp.json()["code"] == code

    import packages.db.session as session_module

    session_module._engine = None
    session_module._sessionmaker = None
    get_settings.cache_clear()


async def test_payment_page_404_when_code_missing(monkeypatch, tmp_path) -> None:
    await _setup(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/pay/NOPE")
    assert response.status_code == 404

    import packages.db.session as session_module

    session_module._engine = None
    session_module._sessionmaker = None
    get_settings.cache_clear()
