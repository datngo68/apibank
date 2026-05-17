from datetime import UTC, datetime, timedelta
from decimal import Decimal

from packages.core.matcher import (
    MatchCandidate,
    MatchInput,
    find_order_match,
    normalize_payment_text,
)


def test_normalize_payment_text_removes_accents_spaces_and_case() -> None:
    assert normalize_payment_text("Thanh toán ĐH4fk9a2") == "thanhtoandh4fk9a2"


def test_normalize_payment_text_strips_punctuation_and_separators() -> None:
    """Ngân hàng thường chèn `-`, `.`, `/`, `:`, `,` vào nội dung CK."""
    assert normalize_payment_text("CK -DH/JWM6YB-") == "ckdhjwm6yb"
    assert normalize_payment_text("DH.JWM6YB.Trace123") == "dhjwm6ybtrace123"
    assert normalize_payment_text("DH:JWM6YB | NAP VI") == "dhjwm6ybnapvi"


def test_find_order_match_handles_inserted_separators_around_code() -> None:
    """Match phải hoạt động ngay cả khi ngân hàng thêm ký tự vào trước/sau mã."""
    now = datetime.now(UTC)
    candidate = MatchCandidate(
        id="ord_1",
        code="DHJWM6YB",
        amount=Decimal("100000"),
        status="pending",
        expired_at=now + timedelta(minutes=15),
    )
    contents = [
        "CUSTOMER -DHJWM6YB- Trace12345",
        "Nap vi DH.JWM6YB",
        "TT/DHJWM6YB/CKKH",
        "DHJWM6YB ma giao dich Trace 99999",
    ]
    for content in contents:
        result = find_order_match(
            MatchInput(amount=Decimal("100000"), content=content), [candidate], now=now
        )
        assert result.status == "matched", content
        assert result.order_id == "ord_1"


def test_find_order_match_returns_unique_pending_order_by_amount_and_code() -> None:
    now = datetime.now(UTC)
    tx = MatchInput(amount=Decimal("150000"), content="NAP TIEN DH4FK9A2")
    orders = [
        MatchCandidate(
            id="ord_1",
            code="DH4FK9A2",
            amount=Decimal("150000"),
            status="pending",
            expired_at=now + timedelta(minutes=15),
        ),
        MatchCandidate(
            id="ord_2",
            code="DHZZ9999",
            amount=Decimal("150000"),
            status="pending",
            expired_at=now + timedelta(minutes=15),
        ),
    ]

    result = find_order_match(tx, orders, now=now)

    assert result.status == "matched"
    assert result.order_id == "ord_1"


def test_find_order_match_marks_ambiguous_when_multiple_candidates_match() -> None:
    now = datetime.now(UTC)
    tx = MatchInput(amount=Decimal("100000"), content="PAY DH111111 DH222222")
    orders = [
        MatchCandidate(
            "ord_1", "DH111111", Decimal("100000"), "pending", now + timedelta(minutes=15)
        ),
        MatchCandidate(
            "ord_2", "DH222222", Decimal("100000"), "pending", now + timedelta(minutes=15)
        ),
    ]

    result = find_order_match(tx, orders, now=now)

    assert result.status == "ambiguous"
    assert result.order_id is None


def test_find_order_match_ignores_expired_and_wrong_amount_orders() -> None:
    now = datetime.now(UTC)
    tx = MatchInput(amount=Decimal("100000"), content="PAY DH111111")
    orders = [
        MatchCandidate(
            "ord_1", "DH111111", Decimal("200000"), "pending", now + timedelta(minutes=15)
        ),
        MatchCandidate(
            "ord_2", "DH111111", Decimal("100000"), "pending", now - timedelta(seconds=1)
        ),
    ]

    result = find_order_match(tx, orders, now=now)

    assert result.status == "unmatched"
    assert result.order_id is None
