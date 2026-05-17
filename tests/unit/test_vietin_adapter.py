"""Test cho VietinBank adapter — chỉ test phần mapping (không cần network).

Phần login/HTTP sẽ được hoàn thiện sau khi capture DevTools.
"""

from __future__ import annotations

from decimal import Decimal

from packages.banks.vietin.adapter import (
    VietinAdapter,
    _extract_items,
    _parse_amount,
    _parse_datetime,
    map_vietin_transaction,
)


def test_vietin_adapter_bank_code() -> None:
    adapter = VietinAdapter(username="u", password="p")
    assert adapter.bank_code == "VTB"


def test_vietin_parse_amount_handles_commas_and_spaces() -> None:
    assert _parse_amount("10,000") == Decimal("10000")
    assert _parse_amount(" 1 500 000 ") == Decimal("1500000")
    assert _parse_amount("") == Decimal("0")
    assert _parse_amount("not-a-number") == Decimal("0")


def test_vietin_parse_datetime_returns_utc_for_vn_format() -> None:
    # 17/05/2026 01:30 VN = 16/05/2026 18:30 UTC
    parsed = _parse_datetime("17/05/2026 01:30:00")
    assert parsed.utcoffset().total_seconds() == 0
    assert parsed.year == 2026
    assert parsed.month == 5
    assert parsed.day == 16
    assert parsed.hour == 18
    assert parsed.minute == 30


def test_vietin_extract_items_handles_nested_shapes() -> None:
    assert _extract_items([{"a": 1}, {"b": 2}]) == [{"a": 1}, {"b": 2}]
    assert _extract_items({"transactions": [{"a": 1}]}) == [{"a": 1}]
    assert _extract_items({"data": {"items": [{"x": 1}]}}) == [{"x": 1}]
    assert _extract_items({"empty": None}) == []


def test_map_vietin_credit_transaction() -> None:
    raw = {
        "refNo": "VTB123456",
        "transDate": "17/05/2026 01:03:00",
        "creditAmount": "10,000",
        "debitAmount": "0",
        "description": "NAP TIEN DHUZEXEE",
        "counterAccount": "0123456789",
        "counterName": "NGUYEN VAN A",
    }
    tx = map_vietin_transaction(raw)
    assert tx.bank_ref_no == "VTB123456"
    assert tx.amount == Decimal("10000")
    assert tx.content == "NAP TIEN DHUZEXEE"
    assert tx.counter_account == "0123456789"
    assert tx.counter_name == "NGUYEN VAN A"
    assert tx.posted_at.day == 16  # đã convert sang UTC


def test_map_vietin_debit_transaction_uses_negative_amount() -> None:
    raw = {
        "refNo": "VTB99",
        "transDate": "16/05/2026",
        "creditAmount": "0",
        "debitAmount": "5000",
        "description": "PHI DICH VU",
    }
    tx = map_vietin_transaction(raw)
    assert tx.amount == Decimal("-5000")
