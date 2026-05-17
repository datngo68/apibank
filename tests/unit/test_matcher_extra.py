from datetime import UTC, datetime, timedelta
from decimal import Decimal

from packages.core.matcher import (
    MatchCandidate,
    MatchInput,
    find_order_match,
    normalize_payment_text,
)


def test_normalize_handles_capital_d_with_stroke() -> None:
    assert normalize_payment_text("Đơn") == "don"


def test_match_unmatched_when_no_orders() -> None:
    result = find_order_match(MatchInput(amount=Decimal("100"), content="x"), [])

    assert result.status == "unmatched"


def test_match_uses_naive_now_as_utc() -> None:
    naive_now = datetime(2026, 5, 16, 12)
    candidate = MatchCandidate(
        id="o1",
        code="DH1",
        amount=Decimal("100"),
        status="pending",
        expired_at=naive_now + timedelta(minutes=5),
    )

    result = find_order_match(
        MatchInput(amount=Decimal("100"), content="DH1"), [candidate], now=naive_now
    )

    assert result.status == "matched"


def test_match_treats_naive_expired_at_as_utc() -> None:
    aware_now = datetime.now(UTC)
    candidate = MatchCandidate(
        id="o1",
        code="DH1",
        amount=Decimal("100"),
        status="pending",
        expired_at=aware_now.replace(tzinfo=None) + timedelta(minutes=5),
    )

    result = find_order_match(
        MatchInput(amount=Decimal("100"), content="DH1"), [candidate], now=aware_now
    )

    assert result.status == "matched"
