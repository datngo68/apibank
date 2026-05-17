from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

OrderStatus = Literal["pending", "paid", "expired", "canceled", "review"]
MatchStatus = Literal["matched", "unmatched", "ambiguous"]


# Mọi ký tự không phải chữ cái/chữ số ASCII đều bị strip:
# space, dấu câu (-./,:;|*), tab, newline, ký hiệu đặc biệt...
# Ngân hàng (đặc biệt MB/BIDV) thường chèn các ký tự này vào nội dung CK,
# vd `DH-JWM6YB`, `DH.JWM6YB`, `DH/JWM6YB CK Trace12345`.
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class MatchInput:
    amount: Decimal
    content: str


@dataclass(frozen=True)
class MatchCandidate:
    id: str
    code: str
    amount: Decimal
    status: OrderStatus
    expired_at: datetime


@dataclass(frozen=True)
class MatchResult:
    status: MatchStatus
    order_id: str | None = None


def normalize_payment_text(value: str) -> str:
    """Chuẩn hoá nội dung CK để so khớp mã đơn.

    Quy trình:
    - NFD strip dấu (`Đơn` -> `Don`).
    - Map `đ`/`Đ` thủ công (NFD không xử lý).
    - Lower-case toàn bộ.
    - Loại bỏ MỌI ký tự không phải `[a-z0-9]` (space, dấu câu, ký hiệu).

    Nhờ vậy ngân hàng thêm/chèn `-`, `.`, `/`, ` ` vào nội dung CK đều
    không ảnh hưởng đến matching. Mã đơn (chỉ gồm chữ + số) sẽ luôn xuất
    hiện như một chuỗi liền sau khi normalize.
    """
    normalized = unicodedata.normalize("NFD", value)
    without_accents = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    without_accents = without_accents.replace("đ", "d").replace("Đ", "D")
    return _NON_ALNUM.sub("", without_accents.lower())


def find_order_match(
    transaction: MatchInput,
    orders: list[MatchCandidate],
    *,
    now: datetime | None = None,
) -> MatchResult:
    current_time = now or datetime.now(UTC)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=UTC)
    normalized_content = normalize_payment_text(transaction.content)

    def _expired_at(order: MatchCandidate) -> datetime:
        if order.expired_at.tzinfo is None:
            return order.expired_at.replace(tzinfo=UTC)
        return order.expired_at

    matches = [
        order
        for order in orders
        if order.status == "pending"
        and _expired_at(order) > current_time
        and order.amount == transaction.amount
        and normalize_payment_text(order.code) in normalized_content
    ]

    if len(matches) == 1:
        return MatchResult(status="matched", order_id=matches[0].id)
    if len(matches) > 1:
        return MatchResult(status="ambiguous")
    return MatchResult(status="unmatched")
