"""Runtime config helper — đọc/ghi AppConfig với encrypt nhạy cảm và cache.

Dùng cho SMTP, Google OAuth, Telegram bot. Admin có thể chỉnh từ UI mà không
cần restart. Hot path (login Google, send email, gửi telegram) gọi `get_decrypted`
được phục vụ qua TTL cache 30s nội bộ.

Quy ước key:
    smtp        {host, port, user, password_enc, from_addr, use_tls, enabled}
    google_oauth {client_id, client_secret_enc, redirect_uri, enabled}
    telegram    {bot_token_enc, webhook_url, webhook_secret, admin_chat_id, enabled}
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from packages.config.settings import get_settings
from packages.db.models import AppConfig, utcnow
from packages.security.crypto import FernetCipher

_CACHE_TTL_SECONDS = 30.0
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _cipher() -> FernetCipher | None:
    keys = get_settings().fernet_keys
    return FernetCipher.from_keys(keys) if keys else None


def invalidate(key: str | None = None) -> None:
    """Clear cache. Gọi sau mỗi `set_config`."""
    if key is None:
        _cache.clear()
    else:
        _cache.pop(key, None)


async def get_config(session: AsyncSession, key: str) -> dict[str, Any]:
    """Đọc raw value_json. KHÔNG decrypt — chỉ trả về như đã lưu."""
    row = await session.get(AppConfig, key)
    if row is None:
        return {}
    return dict(row.value_json or {})


async def get_decrypted(
    session: AsyncSession, key: str, encrypted_fields: Iterable[str] = ()
) -> dict[str, Any]:
    """Đọc + decrypt các field `*_enc` thành field gốc (bỏ hậu tố _enc).

    Có cache 30s. Lỗi decrypt → field set None để tránh crash hot path.
    """
    now = time.monotonic()
    cached = _cache.get(key)
    if cached is not None and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return dict(cached[1])

    row = await session.get(AppConfig, key)
    if row is None:
        result: dict[str, Any] = {}
        _cache[key] = (now, result)
        return dict(result)

    payload = dict(row.value_json or {})
    cipher = _cipher()
    for field in encrypted_fields:
        enc_key = f"{field}_enc"
        token = payload.pop(enc_key, None)
        if token and cipher is not None:
            try:
                payload[field] = cipher.decrypt(token)
            except Exception:  # noqa: BLE001
                payload[field] = None
        else:
            payload.setdefault(field, None)
    _cache[key] = (now, payload)
    return dict(payload)


async def set_config(
    session: AsyncSession,
    key: str,
    value: dict[str, Any],
    *,
    actor_id: str | None = None,
    encrypt_fields: Iterable[str] = (),
    preserve_empty_secrets: bool = True,
) -> dict[str, Any]:
    """Ghi cấu hình. Field trong `encrypt_fields`:
    - nếu value[field] là str non-empty → encrypt và lưu vào `<field>_enc`.
    - nếu value[field] là "" hoặc None và `preserve_empty_secrets=True`:
      giữ nguyên giá trị `<field>_enc` cũ (UX "để trống = giữ nguyên").
    """
    cipher = _cipher()

    row = await session.get(AppConfig, key)
    existing = dict(row.value_json or {}) if row is not None else {}

    new_value: dict[str, Any] = dict(existing)
    encrypt_set = set(encrypt_fields)

    for field, val in value.items():
        if field in encrypt_set:
            if val in (None, ""):
                if not preserve_empty_secrets:
                    new_value.pop(f"{field}_enc", None)
                # else: giữ nguyên
                continue
            if cipher is None:
                raise RuntimeError(
                    "APIBANK_FERNET_KEYS not set — cannot encrypt secret"
                )
            new_value[f"{field}_enc"] = cipher.encrypt(str(val))
        else:
            new_value[field] = val

    if row is None:
        row = AppConfig(key=key, value_json=new_value, updated_by=actor_id)
        session.add(row)
    else:
        row.value_json = new_value
        row.updated_by = actor_id
        row.updated_at = utcnow()

    await session.flush()
    invalidate(key)
    return new_value


def public_view(
    payload: dict[str, Any], encrypted_fields: Iterable[str] = ()
) -> dict[str, Any]:
    """Phiên bản trả về cho FE: bỏ field `*_enc`, thay bằng `<field>_set: bool`."""
    out: dict[str, Any] = {}
    enc_set = set(encrypted_fields)
    for k, v in payload.items():
        if k.endswith("_enc"):
            base = k[:-4]
            if base in enc_set:
                out[f"{base}_set"] = bool(v)
            continue
        out[k] = v
    for field in enc_set:
        out.setdefault(f"{field}_set", False)
    return out


__all__ = [
    "get_config",
    "get_decrypted",
    "set_config",
    "invalidate",
    "public_view",
]
