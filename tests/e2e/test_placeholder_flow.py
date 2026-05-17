from packages.webhook.signing import sign_payload, verify_signature


def test_e2e_webhook_signature_flow() -> None:
    body = b'{"id":"evt_1","type":"payment.succeeded"}'
    header = sign_payload(secret="secret", body=body, timestamp=1_800_000_000)

    assert verify_signature(secret="secret", body=body, header=header, now=1_800_000_001)
