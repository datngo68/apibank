"""Webhook utilities: URL safety + secret decryption.

Tách riêng để cả route create/update + dispatcher đều dùng được.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from packages.config.settings import get_settings
from packages.security.crypto import FernetCipher

__all__ = [
    "is_safe_webhook_url",
    "validate_webhook_url",
    "encrypt_webhook_secret",
    "decrypt_webhook_secret",
]


def _is_private_or_loopback(host: str) -> bool:
    """Trả True nếu hostname/IP rơi vào dải private, loopback, link-local hoặc multicast.

    Resolve DNS một lần để chống DNS rebinding cơ bản (vẫn cần outbound firewall
    cho phòng tuyến cuối). Nếu host không resolve được → an toàn coi như private.
    """
    try:
        addr = ipaddress.ip_address(host)
        return _is_blocked_ip(addr)
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return True
    for _family, _type, _proto, _canon, sockaddr in infos:
        ip_text = sockaddr[0]
        try:
            ip_obj = ipaddress.ip_address(ip_text)
        except ValueError:
            continue
        if _is_blocked_ip(ip_obj):
            return True
    return False


def _is_blocked_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def is_safe_webhook_url(url: str) -> tuple[bool, str | None]:
    """Validate URL webhook outbound.

    - Phải có scheme http hoặc https.
    - Hostname không rỗng.
    - Resolve DNS không trỏ tới dải private/loopback/link-local/multicast.

    Trả `(ok, reason_if_blocked)`.
    """
    if not url:
        return False, "url rỗng"
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        return False, f"scheme '{parsed.scheme}' không được hỗ trợ (chỉ http/https)"
    host = parsed.hostname
    if not host:
        return False, "thiếu hostname"
    # Cho phép explicit cờ env để bật private URL trong test/dev.
    settings = get_settings()
    if getattr(settings, "is_production", False) is False:
        # Local/dev: vẫn chặn metadata 169.254.169.254 — nguy hiểm phổ quát.
        try:
            addr = ipaddress.ip_address(host)
            if addr.is_link_local:
                return False, "URL trỏ tới link-local (metadata service) bị cấm"
        except ValueError:
            pass
        return True, None
    if _is_private_or_loopback(host):
        return False, "URL trỏ tới dải private/loopback/link-local"
    return True, None


def validate_webhook_url(url: str) -> str:
    """Helper raise ValueError với thông điệp tiếng Việt nếu URL không an toàn."""
    ok, reason = is_safe_webhook_url(url)
    if not ok:
        raise ValueError(f"URL webhook không an toàn: {reason}")
    return url


def encrypt_webhook_secret(secret: str) -> str:
    """Mã hóa secret webhook bằng Fernet. Bắt buộc Fernet keys có trong settings.

    KHÔNG fallback lưu plain — silent fallback từng gây bug ký HMAC sai. Nếu
    `APIBANK_FERNET_KEYS` rỗng, raise RuntimeError yêu cầu admin cấu hình trước.
    """
    keys = get_settings().fernet_keys
    if not keys:
        raise RuntimeError(
            "APIBANK_FERNET_KEYS chưa cấu hình; không thể lưu secret webhook an toàn. "
            "Chạy `apimb fernet generate` rồi cập nhật .env."
        )
    return FernetCipher.from_keys(keys).encrypt(secret)


def decrypt_webhook_secret(secret_enc: str) -> str:
    """Giải mã secret webhook đã encrypt bằng Fernet.

    Nếu `secret_enc` là plain text (legacy data trước khi fix), thử Fernet decrypt
    trước; nếu fail và có khả năng plain (không có Fernet keys hoặc decode lỗi),
    trả nguyên text — caller có thể flag cảnh báo.
    """
    keys = get_settings().fernet_keys
    if not keys:
        return secret_enc
    try:
        return FernetCipher.from_keys(keys).decrypt(secret_enc)
    except Exception:  # noqa: BLE001 — Fernet raises InvalidToken; legacy plain → fallback
        return secret_enc
