from __future__ import annotations

from decimal import Decimal

from packages.crypto.callbacks import sign_payload, verify_signature
from packages.crypto.invoices import normalize_address
from packages.crypto.watchers.evm import raw_to_decimal, topic_to_address
from packages.crypto.watchers.tron import raw_to_decimal as tron_raw_to_decimal


def test_crypto_callback_signature_roundtrip() -> None:
    raw_body = '{"event":"crypto.invoice.completed"}'
    signature = sign_payload("secret", "2026-07-01T00:00:00Z", raw_body)
    assert verify_signature("secret", "2026-07-01T00:00:00Z", raw_body, signature)
    assert not verify_signature("secret", "2026-07-01T00:00:00Z", raw_body + "x", signature)


def test_evm_log_helpers_parse_transfer_values() -> None:
    topic = "0x00000000000000000000000083846bb147b4a07b81c99298e76e43416a18dc45"
    assert topic_to_address(topic) == "0x83846bb147b4a07b81c99298e76e43416a18dc45"
    assert raw_to_decimal("0xde0b6b3a7640000", 18) == Decimal("1")


def test_tron_raw_to_decimal() -> None:
    assert tron_raw_to_decimal("1000000", 6) == Decimal("1")


def test_normalize_address_keeps_tron_case_but_lowers_evm() -> None:
    assert normalize_address("0xABC", "evm") == "0xabc"
    assert normalize_address("TAbC", "tron") == "TAbC"
