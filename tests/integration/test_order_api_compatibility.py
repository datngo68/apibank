from decimal import Decimal
from unittest.mock import patch

import httpx
from sqlalchemy import select

from apps.api.main import create_app
from packages.core.ingest import _build_payload
from packages.db.models import ApiKey, BankAccount, Order, Transaction, User
from packages.security.dependencies import enforce_subscription_and_quota
from packages.security.user_auth import current_user


async def test_order_public_code_matches_transfer_content(initialized_db):
    session = initialized_db
    user = User(id="compat-user", email="compat@example.test", password_hash="unused")
    bank = BankAccount(
        id="compat-bank", user_id=user.id, bank_code="MB", account_no="1234567",
        account_holder="TEST", credentials_enc="unused", status="active",
    )
    session.add_all([user, bank])
    await session.commit()
    app = create_app()
    key = ApiKey(id="compat-key", scopes=["admin:*"], key_hash="unused", owner_id="test")
    app.dependency_overrides[enforce_subscription_and_quota] = lambda: key
    app.dependency_overrides[current_user] = lambda: user
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        await client.get("/healthz")
        headers = {
            "Idempotency-Key": "compat-order",
            "X-CSRF-Token": client.cookies.get("apibank_csrf", ""),
        }
        payload = {"amount_vnd": 50000, "bank_account_id": bank.id}
        with patch("packages.banks.poll_kick.kick"):
            response = await client.post("/v1/orders", json=payload, headers=headers)
        assert response.status_code == 201, response.text
        body = response.json()
        stored = await session.get(Order, body["id"])
        assert stored.code.startswith("PAY")
        assert body["code"] == stored.transfer_content == body["transfer_content"]
        assert body["code"].endswith(" chuyen tien")
        assert body["pay_url"] == f"/pay/{stored.code}"
        assert (await client.get(f"/v1/orders/{stored.id}")).json()["code"] == body["code"]
        assert (await client.get("/api/v1/me/orders")).json()[0]["code"] == body["code"]
        replay = await client.post("/v1/orders", json=payload, headers=headers)
        assert replay.status_code == 200
        assert replay.json() == body
        assert len((await session.scalars(select(Order))).all()) == 1
        page = await client.get(body["pay_url"])
        assert page.status_code == 200
        assert stored.transfer_content in page.text
        with patch("apps.api.routes.qr.generate_vietqr_payload", return_value="test") as qr:
            with patch("apps.api.routes.qr.generate_qr_png", return_value=b"png"):
                assert (await client.get(f"/qr/{stored.id}.png")).status_code == 200
            assert qr.call_args.kwargs["content"] == body["code"]
        tx = Transaction(id="compat-tx", bank_ref_no="test", amount_vnd=Decimal(50000))
        webhook = _build_payload(stored, tx)["data"]
        assert webhook["code"] == webhook["order"]["code"] == body["code"]
        legacy = Order.new(amount_vnd=Decimal(100), bank_account_id=bank.id, ttl_seconds=900)
        legacy.code = "DH123456"
        legacy.transfer_content = None
        session.add(legacy)
        await session.commit()
        legacy_body = (await client.get(f"/v1/orders/{legacy.id}")).json()
        assert legacy_body["code"] == "DH123456"
        assert legacy_body["pay_url"] == "/pay/DH123456"
        # Human names may be reused; never resolve a payment URL to an arbitrary order.
        assert (await client.get(f"/pay/{body['code']}")).status_code == 404
