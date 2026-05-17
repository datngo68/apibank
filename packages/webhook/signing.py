from __future__ import annotations

import hmac
from hashlib import sha256


def sign_payload(*, secret: str, body: bytes, timestamp: int) -> str:
    signed_payload = str(timestamp).encode() + b"." + body
    digest = hmac.new(secret.encode(), signed_payload, sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def verify_signature(
    *,
    secret: str,
    body: bytes,
    header: str,
    now: int,
    tolerance_seconds: int = 300,
) -> bool:
    parts = dict(item.split("=", 1) for item in header.split(",") if "=" in item)
    timestamp_text = parts.get("t")
    signature = parts.get("v1")
    if timestamp_text is None or signature is None:
        return False
    try:
        timestamp = int(timestamp_text)
    except ValueError:
        return False
    if abs(now - timestamp) > tolerance_seconds:
        return False
    expected = sign_payload(secret=secret, body=body, timestamp=timestamp).split("v1=", 1)[1]
    return hmac.compare_digest(expected, signature)
