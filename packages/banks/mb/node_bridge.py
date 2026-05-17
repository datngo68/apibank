from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx

from packages.banks.base import BankAuthError, BankError, BankTransaction


class MBNodeBridgeAdapter:
    bank_code = "MB"

    def __init__(self, *, base_url: str, timeout: float = 15.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout)

    async def login(self) -> None:
        try:
            response = await self._client.post("/login")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise BankAuthError(str(exc)) from exc

    async def health(self) -> bool:
        try:
            response = await self._client.post("/login")
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    async def get_balance(self, account_no: str) -> Decimal:
        response = await self._client.get(f"/balance/{account_no}")
        response.raise_for_status()
        payload = response.json()
        return Decimal(str(payload["balance"]))

    async def list_transactions(
        self, account_no: str, start: datetime, end: datetime
    ) -> AsyncIterator[BankTransaction]:
        params = {
            "from": start.strftime("%d/%m/%Y"),
            "to": end.strftime("%d/%m/%Y"),
        }
        response = await self._client.get(f"/transactions/{account_no}", params=params)
        if response.status_code >= 400:
            raise BankError(response.text)
        for raw in response.json().get("transactions", []):
            yield self._map_transaction(raw)

    @staticmethod
    def _map_transaction(raw: dict[str, Any]) -> BankTransaction:
        amount = Decimal(str(raw.get("amount") or raw.get("creditAmount") or 0))
        if amount == 0:
            amount = -Decimal(str(raw.get("debitAmount") or 0))
        posted_text = raw.get("postedAt") or raw.get("transactionDate")
        posted_at = (
            datetime.fromisoformat(posted_text)
            if posted_text and "T" in posted_text
            else datetime.strptime(posted_text or "01/01/1970", "%d/%m/%Y")
        )
        return BankTransaction(
            bank_ref_no=str(raw.get("refNo") or raw.get("transactionId")),
            posted_at=posted_at,
            amount=amount,
            content=str(raw.get("description") or raw.get("content") or ""),
            counter_account=raw.get("counterAccount"),
            counter_name=raw.get("counterName"),
            raw=raw,
        )
