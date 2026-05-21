"""Smoke tests cho các module mới ở Phase 1-4."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock


def test_permissions_resolve_admin_role() -> None:
    from packages.security.permissions import (
        ROLE_FINANCE,
        ROLE_READ_ONLY,
        ROLE_SUPER_ADMIN,
        has_permission,
        resolve_admin_role,
    )

    legacy_admin = MagicMock(role="admin", admin_role_extra=None)
    assert resolve_admin_role(legacy_admin) == ROLE_SUPER_ADMIN
    assert has_permission(legacy_admin, "user:delete") is True

    finance = MagicMock(role="user", admin_role_extra=ROLE_FINANCE)
    assert resolve_admin_role(finance) == ROLE_FINANCE
    assert has_permission(finance, "billing:refund") is True
    assert has_permission(finance, "user:delete") is False

    read = MagicMock(role="user", admin_role_extra=ROLE_READ_ONLY)
    assert has_permission(read, "audit:read") is True
    assert has_permission(read, "billing:refund") is False

    plain_user = MagicMock(role="user", admin_role_extra=None)
    assert resolve_admin_role(plain_user) == ROLE_READ_ONLY


async def test_captcha_disabled_returns_true(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Khi captcha_secret rỗng, verify_captcha luôn trả True."""
    import packages.security.captcha as captcha
    from packages.config.settings import get_settings

    monkeypatch.setenv("APIBANK_CAPTCHA_SECRET", "")
    get_settings.cache_clear()
    try:
        cfg = captcha.captcha_public_config()
        assert cfg["enabled"] is False
        ok = await captcha.verify_captcha(None)
        assert ok is True
    finally:
        get_settings.cache_clear()


def test_pii_passthrough_when_disabled(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Khi APIBANK_ENCRYPT_PII=false, helper trả nguyên giá trị."""
    from packages.config.settings import get_settings
    from packages.security import pii

    monkeypatch.setenv("APIBANK_ENCRYPT_PII", "false")
    get_settings.cache_clear()
    pii.reset_cache_for_tests()
    try:
        assert pii.encrypt_pii("hello") == "hello"
        assert pii.decrypt_pii("hello") == "hello"
        assert pii.encrypt_pii(None) is None
        d = pii.encrypt_pii_dict({"email": "x@a.com", "n": 3})
        assert d == {"email": "x@a.com", "n": 3}
    finally:
        get_settings.cache_clear()
        pii.reset_cache_for_tests()


def test_pii_roundtrip_when_enabled(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from packages.config.settings import get_settings
    from packages.security import pii

    monkeypatch.setenv("APIBANK_ENCRYPT_PII", "true")
    monkeypatch.setenv(
        "APIBANK_FERNET_KEYS",
        "primary:NhnFbDTpYks-q2AmJsBhuG_iL6VDaKL14L4vy44ZqkM=",
    )
    get_settings.cache_clear()
    pii.reset_cache_for_tests()
    try:
        enc = pii.encrypt_pii("plain-value")
        assert enc is not None and enc.startswith("enc:v1:")
        assert pii.decrypt_pii(enc) == "plain-value"

        enc_d = pii.encrypt_pii_dict({"a": "secret", "b": 2})
        assert isinstance(enc_d["a"], str) and enc_d["a"].startswith("enc:v1:")
        dec_d = pii.decrypt_pii_dict(enc_d)
        assert dec_d == {"a": "secret", "b": 2}
    finally:
        get_settings.cache_clear()
        pii.reset_cache_for_tests()


def test_classify_endpoint() -> None:
    from apps.api.middleware.usage_metering import classify_endpoint

    assert classify_endpoint("/v1/orders", "POST") == "orders.create"
    assert classify_endpoint("/v1/orders/abc", "GET") == "orders.read"
    assert classify_endpoint("/v1/transactions", "GET") == "transactions.list"
    assert classify_endpoint("/v1/webhooks", "POST").startswith("webhooks.")
    assert classify_endpoint("/healthz", "GET") == "other"
    assert classify_endpoint("/v1/foo", "GET") == "v1.foo"


def test_request_context_filter() -> None:
    import logging

    from packages.obs.context import (
        RequestContextFilter,
        request_id_var,
        route_var,
        user_id_var,
    )

    flt = RequestContextFilter()
    record = logging.LogRecord(
        "test", logging.INFO, "f", 1, "msg", None, None
    )
    request_id_var.set("rid-1")
    user_id_var.set("user-1")
    route_var.set("/v1/orders")
    assert flt.filter(record) is True
    assert record.request_id == "rid-1"
    assert record.user_id == "user-1"
    assert record.route == "/v1/orders"


def test_legal_data_export_helper_exists() -> None:
    from packages.compliance import data_export

    assert callable(data_export.build_zip_for_user)


def test_invoice_pdf_helper_exists() -> None:
    from packages.billing import invoice_pdf

    assert callable(invoice_pdf.generate)


def test_decimals_module_smoke() -> None:
    """Smoke import: phase 4 model module load."""
    from packages.db.models import (
        BillingProfile,
        DataExportRequest,
        IpBlocklist,
        LegalVersion,
        NotificationTemplate,
        SecurityEvent,
        SupportTicket,
        TermsAcceptance,
        TicketMessage,
        UserNote,
        UserTag,
        WithdrawalRequest,
    )

    assert all(
        cls.__tablename__
        for cls in (
            BillingProfile,
            DataExportRequest,
            IpBlocklist,
            LegalVersion,
            NotificationTemplate,
            SecurityEvent,
            SupportTicket,
            TermsAcceptance,
            TicketMessage,
            UserNote,
            UserTag,
            WithdrawalRequest,
        )
    )
    # Khử warning F401
    _ = (datetime, Decimal)
