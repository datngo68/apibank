from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal

from packages.banks.base import BankTransaction


class ACBAdapter:
    bank_code = "ACB"

    async def login(self) -> None:
        raise NotImplementedError("roadmap")

    async def health(self) -> bool:
        return False

    async def get_balance(self, account_no: str) -> Decimal:
        raise NotImplementedError("roadmap")

    async def list_transactions(
        self, account_no: str, start: datetime, end: datetime
    ) -> AsyncIterator[BankTransaction]:
        raise NotImplementedError("roadmap")
        yield
