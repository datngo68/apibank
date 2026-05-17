from packages.webhook.signing import sign_payload, verify_signature


def test_verify_rejects_missing_v1_segment() -> None:
    assert not verify_signature(secret="x", body=b"{}", header="t=1", now=1)


def test_verify_rejects_invalid_timestamp() -> None:
    assert not verify_signature(secret="x", body=b"{}", header="t=abc,v1=ff", now=1)


def test_verify_rejects_signature_mismatch() -> None:
    body = b"{}"
    header = sign_payload(secret="x", body=body, timestamp=1_800_000_000)
    tampered = header.replace("v1=", "v1=ff")
    assert not verify_signature(secret="x", body=body, header=tampered, now=1_800_000_000)
