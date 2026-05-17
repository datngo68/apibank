"""Password hashing dùng bcrypt với cost mặc định 12.

Bcrypt giới hạn 72 byte; pre-hash bằng SHA-256 trước khi bcrypt để tránh truncation
nhưng vẫn deterministic. Đây là pattern chuẩn dùng bởi Django, Devise...
"""

from __future__ import annotations

import base64
import hashlib

import bcrypt

DEFAULT_ROUNDS = 12
_BCRYPT_PREFIX = "$bcrypt-sha256$"


def _prehash(password: str) -> bytes:
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    # base64 để bcrypt không thấy NUL byte (NUL kết thúc chuỗi)
    return base64.b64encode(digest)


def hash_password(password: str, *, rounds: int = DEFAULT_ROUNDS) -> str:
    if not password:
        raise ValueError("password must not be empty")
    salt = bcrypt.gensalt(rounds=rounds)
    digest = bcrypt.hashpw(_prehash(password), salt).decode("ascii")
    return f"{_BCRYPT_PREFIX}{digest}"


def verify_password(password: str, hashed: str) -> bool:
    if not hashed or not password:
        return False
    if hashed.startswith(_BCRYPT_PREFIX):
        digest = hashed[len(_BCRYPT_PREFIX):].encode("ascii")
        try:
            return bcrypt.checkpw(_prehash(password), digest)
        except ValueError:
            return False
    # Fallback cho hash bcrypt thuần (legacy / migration)
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], hashed.encode("ascii"))
    except ValueError:
        return False


def needs_rehash(hashed: str, *, rounds: int = DEFAULT_ROUNDS) -> bool:
    """True nếu hash dùng cost cũ hoặc thuật toán cũ và nên rehash khi user login."""
    if not hashed:
        return True
    if not hashed.startswith(_BCRYPT_PREFIX):
        return True
    body = hashed[len(_BCRYPT_PREFIX):]
    parts = body.split("$")
    if len(parts) < 4:
        return True
    try:
        current = int(parts[2])
    except ValueError:
        return True
    return current < rounds
