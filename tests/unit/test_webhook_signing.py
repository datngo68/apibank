from packages.webhook.signing import sign_payload, verify_signature


def test_signature_verifies_matching_payload() -> None:
    body = b'{"type":"payment.succeeded"}'
    header = sign_payload(secret="super-secret", body=body, timestamp=1_800_000_000)

    assert verify_signature(secret="super-secret", body=body, header=header, now=1_800_000_030)


def test_signature_rejects_stale_timestamp() -> None:
    body = b"{}"
    header = sign_payload(secret="super-secret", body=body, timestamp=1_800_000_000)

    assert not verify_signature(secret="super-secret", body=body, header=header, now=1_800_001_000)
