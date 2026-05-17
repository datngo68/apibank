"""Tiện ích sinh, hash, kiểm tra recovery-code dùng cho 2FA TOTP.

Mỗi user có ~10 mã 8 ký tự, được hash khi lưu (như password). Khi user nhập đúng
1 mã, mã đó bị đánh dấu used; mã khác vẫn còn. Khi hết, user phải re-enroll.
"""

from __future__ import annotations

import base64
import secrets
from io import BytesIO

import bcrypt
import pyotp
import qrcode


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, *, account: str, issuer: str = "APIBank") -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=issuer)


def provisioning_qr_data_uri(otpauth_uri: str, *, box_size: int = 6, border: int = 2) -> str:
    """Sinh QR code PNG cho `otpauth://` URI dưới dạng data URI base64.

    FE chỉ cần gán vào <img src=...>; CSP đã cho phép `img-src data:`. Dùng
    Error Correction Level M (default) — cân bằng giữa kích thước và độ bền
    nhiễu, đủ cho app authenticator quét trên màn hình laptop.
    """
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(otpauth_uri)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def verify_totp(secret: str, code: str, *, valid_window: int = 1) -> bool:
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit() or len(code) != 6:
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=valid_window)


def generate_recovery_codes(count: int = 10) -> list[str]:
    return [_format_code(secrets.token_hex(4)) for _ in range(count)]


def _format_code(raw: str) -> str:
    raw = raw.upper()
    return f"{raw[:4]}-{raw[4:8]}"


def hash_recovery_code(code: str) -> str:
    salt = bcrypt.gensalt(rounds=10)
    return bcrypt.hashpw(code.encode("utf-8"), salt).decode("ascii")


def verify_recovery_code(code: str, hashed: str) -> bool:
    if not code or not hashed:
        return False
    try:
        return bcrypt.checkpw(code.encode("utf-8"), hashed.encode("ascii"))
    except ValueError:
        return False
