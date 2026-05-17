from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol


class BankError(Exception):
    pass


class BankAuthError(BankError):
    pass


class BankRateLimited(BankError):
    pass


class BankNotSupportedError(BankError):
    """Bank code chưa có adapter hoạt động (vd BIDV/ACB/VCB chỉ là stub)."""

    pass


@dataclass(frozen=True)
class BankTransaction:
    bank_ref_no: str
    posted_at: datetime
    amount: Decimal
    content: str
    counter_account: str | None
    counter_name: str | None
    raw: dict[str, Any]

    def __post_init__(self) -> None:
        if self.amount == 0:
            raise ValueError("amount must be non-zero")
        if not self.bank_ref_no:
            raise ValueError("bank_ref_no is required")


class BankAdapter(Protocol):
    bank_code: str

    async def login(self) -> None: ...

    async def health(self) -> bool: ...

    async def get_balance(self, account_no: str) -> Decimal: ...

    def list_transactions(
        self, account_no: str, start: datetime, end: datetime
    ) -> AsyncIterator[BankTransaction]: ...
