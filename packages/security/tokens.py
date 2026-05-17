"""Token helpers — sinh và băm mã đối xứng (session, email verify, reset...).

Đặc tính:
- Token plain dài đủ entropy (URL-safe).
- Lưu DB chỉ dạng SHA-256 hex (constant-time compare khi verify).
- So sánh bằng `secrets.compare_digest` để tránh timing attack.
"""

from __future__ import annotations

import hashlib
import secrets


def generate_token(length: int = 32) -> str:
    """Sinh token base64url, ~length*1.3 ký tự."""
    return secrets.token_urlsafe(length)


def hash_token(token: str) -> str:
    """SHA-256 hex; dùng cho cột `token_hash` (Session, EmailToken)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return secrets.compare_digest(a, b)
