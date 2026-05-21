"""Helper encrypt/decrypt PII at rest dùng Fernet keys hiện có.

Sử dụng prefix ``enc:v1:`` để phân biệt giá trị đã mã hoá vs plain — khi
admin bật/tắt `APIBANK_ENCRYPT_PII` runtime, code đọc vẫn handle cả hai
trường hợp (backward compat).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from packages.config.settings import get_settings
from packages.security.crypto import FernetCipher

_PREFIX = "enc:v1:"


@lru_cache(maxsize=1)
def _cipher() -> FernetCipher | None:
    settings = get_settings()
    if not settings.fernet_keys:
        return None
    return FernetCipher.from_keys(settings.fernet_keys)


def encrypt_pii(value: str | None) -> str | None:
    """Encrypt nếu setting bật + có Fernet keys. None giữ nguyên."""
    if value is None or value == "":
        return value
    settings = get_settings()
    if not settings.encrypt_pii:
        return value
    cipher = _cipher()
    if cipher is None:
        return value
    if value.startswith(_PREFIX):
        return value  # đã encrypt rồi
    return _PREFIX + cipher.encrypt(value)


def decrypt_pii(value: str | None) -> str | None:
    """Best-effort decrypt; trả nguyên giá trị nếu không phải ciphertext."""
    if value is None or value == "":
        return value
    if not value.startswith(_PREFIX):
        return value
    cipher = _cipher()
    if cipher is None:
        return value  # không decrypt được, trả nguyên ciphertext
    try:
        return cipher.decrypt(value[len(_PREFIX):])
    except Exception:  # noqa: BLE001
        return value


def encrypt_pii_dict(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Encrypt giá trị string trong dict (1 cấp) cho audit_log JSON.

    Chỉ encrypt VALUE; KEY giữ nguyên. Nested dict giữ nguyên (không recurse —
    audit log thường flat).
    """
    if not data:
        return data
    settings = get_settings()
    if not settings.encrypt_pii:
        return data
    cipher = _cipher()
    if cipher is None:
        return data
    out: dict[str, Any] = {}
    for k, v in data.items():
        if isinstance(v, str) and v and not v.startswith(_PREFIX):
            out[k] = _PREFIX + cipher.encrypt(v)
        else:
            out[k] = v
    return out


def decrypt_pii_dict(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if not data:
        return data
    cipher = _cipher()
    if cipher is None:
        return data
    out: dict[str, Any] = {}
    for k, v in data.items():
        if isinstance(v, str) and v.startswith(_PREFIX):
            try:
                out[k] = cipher.decrypt(v[len(_PREFIX):])
            except Exception:  # noqa: BLE001
                out[k] = v
        else:
            out[k] = v
    return out


def reset_cache_for_tests() -> None:
    """For tests đổi setting runtime."""
    _cipher.cache_clear()


__all__ = [
    "encrypt_pii",
    "decrypt_pii",
    "encrypt_pii_dict",
    "decrypt_pii_dict",
    "reset_cache_for_tests",
]
