"""Test dispatcher decrypt webhook.secret_enc trước khi ký HMAC.

Bug cũ: ký bằng ciphertext Fernet → consumer verify với secret gốc luôn fail.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from packages.config.settings import get_settings
from packages.db.models import Order, Transaction, Webhook, WebhookAttempt
from packages.webhook import encrypt_webhook_secret
from packages.webhook.dispatcher import dispatch_due_attempts
from packages.webhook.signing import verify_signature
from tests.helpers.in_memory_db import build_session


@pytest.fixture(autouse=True)
def _fernet_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("APIBANK_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(
        "APIBANK_FERNET_KEYS",
        "primary:NhnFbDTpYks-q2AmJsBhuG_iL6VDaKL14L4vy44ZqkM=",
    )
    get_settings.cache_clear()


async def _seed(  # type: ignore[no-untyped-def]
    session,
    *,
    secret_plain: str = "user-shared-secret",  # noqa: S107
) -> tuple[WebhookAttempt, str]:
    secret_enc = encrypt_webhook_secret(secret_plain)
    webhook = Webhook(
        id="wh_dec",
        owner_id="default",
        url="https://example.test/hook",
        secret_enc=secret_enc,
        active=True,
        headers_json={},
        created_at=datetime.now(UTC),
    )
    order = Order.new(amount_vnd=Decimal("10000"), bank_account_id="ba_x", ttl_seconds=900)
    tx = Transaction(
        bank_account_id="ba_x",
        bank_ref_no="FT_DEC",
        amount_vnd=Decimal("10000"),
        content="ANY",
        posted_at=datetime.now(UTC),
        raw_json={},
        state="matched",
    )
    session.add_all([webhook, order, tx])
    await session.flush()
    attempt = WebhookAttempt.new(
        webhook_id=webhook.id,
        order_id=order.id,
        transaction_id=tx.id,
        payload={"hello": "world"},
    )
    session.add(attempt)
    await session.flush()
    return attempt, secret_plain


@pytest.mark.asyncio
async def test_dispatch_signs_with_decrypted_secret() -> None:
    """Header X-Signature phải verify được với secret gốc, KHÔNG phải secret_enc."""
    captured: dict[str, str | bytes] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["sig"] = request.headers.get("X-Signature", "")
        captured["body"] = bytes(request.content or b"")
        return httpx.Response(200, text="ok")

    async for session in build_session():
        attempt, secret = await _seed(session)
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            await dispatch_due_attempts(session, client=client)
        await session.refresh(attempt)
        assert attempt.status == "delivered"

    sig = str(captured["sig"])
    body = bytes(captured["body"])
    assert sig
    # Verify với secret gốc — phải pass.
    parts = dict(p.split("=", 1) for p in sig.split(",") if "=" in p)
    ts = int(parts["t"])
    assert verify_signature(secret=secret, body=body, header=sig, now=ts)

    # Verify với secret SAI (ví dụ ciphertext) — phải fail.
    assert not verify_signature(secret="wrong-secret", body=body, header=sig, now=ts)
    # Đảm bảo body đúng JSON đã encode.
    payload = json.loads(body)
    assert payload == {"hello": "world"}


@pytest.mark.asyncio
async def test_dispatch_marks_dead_when_url_unsafe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production env + URL link-local → attempt bị đánh dấu dead, không gửi."""
    monkeypatch.setenv("APIBANK_ENVIRONMENT", "production")
    monkeypatch.setenv("APIBANK_API_KEY_SALT", "a" * 48)
    monkeypatch.setenv("APIBANK_SESSION_SECRET_KEY", "b" * 48)
    get_settings.cache_clear()

    async for session in build_session():
        attempt, _ = await _seed(session, secret_plain="s")
        webhook = await session.get(Webhook, "wh_dec")
        assert webhook is not None
        webhook.url = "http://169.254.169.254/latest/meta-data/"
        await session.flush()

        called: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            called.append(str(request.url))  # noqa: B023 — closure over outer list, intentional
            return httpx.Response(200)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            await dispatch_due_attempts(session, client=client)
        await session.refresh(attempt)
        assert attempt.status == "dead"
        assert "unsafe_url" in (attempt.last_error or "")
        assert called == []  # không call ra IMDS
