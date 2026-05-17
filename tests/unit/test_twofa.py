"""Unit tests cho 2FA TOTP."""

from __future__ import annotations

import base64

import pyotp

from packages.security.twofa import (
    generate_recovery_codes,
    generate_totp_secret,
    hash_recovery_code,
    provisioning_qr_data_uri,
    provisioning_uri,
    verify_recovery_code,
    verify_totp,
)


def test_secret_format() -> None:
    s = generate_totp_secret()
    assert len(s) >= 16
    # Base32 chars only
    assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" for c in s)


def test_totp_verifies_current_code() -> None:
    secret = generate_totp_secret()
    code = pyotp.TOTP(secret).now()
    assert verify_totp(secret, code) is True


def test_totp_rejects_invalid_code() -> None:
    secret = generate_totp_secret()
    assert verify_totp(secret, "000000") is False
    assert verify_totp(secret, "abc") is False
    assert verify_totp(secret, "") is False


def test_provisioning_uri_format() -> None:
    uri = provisioning_uri("JBSWY3DPEHPK3PXP", account="ban@example.com")
    assert uri.startswith("otpauth://totp/")
    assert "issuer=APIBank" in uri


def test_provisioning_qr_data_uri_returns_png_base64() -> None:
    secret = "JBSWY3DPEHPK3PXP"
    uri = provisioning_uri(secret, account="ban@example.com")
    data_uri = provisioning_qr_data_uri(uri)
    assert data_uri.startswith("data:image/png;base64,")
    payload = base64.b64decode(data_uri.split(",", 1)[1], validate=True)
    # PNG magic header: 89 50 4E 47 0D 0A 1A 0A
    assert payload[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(payload) > 100  # ảnh QR thực, không phải file rỗng


def test_recovery_codes_unique_and_formatted() -> None:
    codes = generate_recovery_codes(10)
    assert len(set(codes)) == 10
    for code in codes:
        assert len(code) == 9 and code[4] == "-"


def test_recovery_code_hash_round_trip() -> None:
    code = "AAAA-BBBB"
    h = hash_recovery_code(code)
    assert verify_recovery_code(code, h) is True
    assert verify_recovery_code("AAAA-CCCC", h) is False
    assert verify_recovery_code("", h) is False
    assert verify_recovery_code(code, "") is False
