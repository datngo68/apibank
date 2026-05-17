from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any


def hash_api_key(key: str, *, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{key}".encode()).hexdigest()


def generate_api_key(*, prefix: str = "sk_live_") -> str:
    return prefix + secrets.token_urlsafe(32)


def hash_request(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(body).hexdigest()
