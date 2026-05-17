from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from packages.banks.base import BankAuthError, BankTransaction

# MB API filter theo ngày giờ VN. `mbbank-lib` strftime("%d/%m/%Y") không
# convert tz, nên phải đưa start/end sang giờ VN trước khi gọi, tránh bug
# từ ~17h UTC (= 0h VN) trở đi cửa sổ bị lệch 1 ngày và worker mù 7 tiếng.
_VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


class MBAdapter:
    bank_code = "MB"

    def __init__(self, *, username: str, password: str) -> None:
        self._username = username
        self._password = password
        self._client: Any | None = None
        self._ocr: Any | None = None

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from mbbank import CapchaOCR, MBBankAsync
        except ImportError as exc:
            raise RuntimeError("mbbank-lib is not installed") from exc
        if self._ocr is None:
            self._ocr = CapchaOCR()
        self._client = MBBankAsync(
            username=self._username, password=self._password, ocr_class=self._ocr
        )
        return self._client

    async def login(self) -> None:
        client = self._ensure_client()
        last_error: Exception | None = None
        for _ in range(5):
            try:
                image_bytes = await client.get_capcha_image()
                captcha_text = self._ocr.process_image(image_bytes)  # type: ignore[union-attr]
                if not captcha_text:
                    last_error = BankAuthError("ocr returned empty captcha")
                    continue
                await client.login(captcha_text)
                return
            except Exception as exc:
                last_error = exc
        raise BankAuthError(f"login failed after 5 attempts: {last_error!r}") from last_error

    async def health(self) -> bool:
        return self._client is not None and getattr(self._client, "sessionId", None) is not None

    async def get_balance(self, account_no: str) -> Decimal:
        client = self._ensure_client()
        if not await self.health():
            await self.login()
        result = await client.getBalance()
        return Decimal(str(getattr(result, "currentBalance", result)))

    async def list_transactions(
        self, account_no: str, start: datetime, end: datetime
    ) -> AsyncIterator[BankTransaction]:
        client = self._ensure_client()
        if not await self.health():
            await self.login()
        # MB API yêu cầu fromDate/toDate theo giờ VN (lib chỉ strftime, không tz-convert).
        start_vn = start.astimezone(_VN_TZ) if start.tzinfo else start.replace(tzinfo=UTC).astimezone(_VN_TZ)
        end_vn = end.astimezone(_VN_TZ) if end.tzinfo else end.replace(tzinfo=UTC).astimezone(_VN_TZ)
        result = await client.getTransactionAccountHistory(
            accountNo=account_no, from_date=start_vn, to_date=end_vn
        )
        items: list[Any] = []
        if hasattr(result, "transactionHistoryList"):
            items = list(result.transactionHistoryList or [])
        elif hasattr(result, "transactionList"):
            items = list(result.transactionList or [])
        elif isinstance(result, dict):
            items = list(result.get("transactionHistoryList", []))
        for raw in items:
            yield self.map_transaction(_to_dict(raw))

    def map_transaction(self, raw: dict[str, Any]) -> BankTransaction:
        credit = _parse_amount(raw.get("creditAmount") or raw.get("credit_amount") or 0)
        debit = _parse_amount(raw.get("debitAmount") or raw.get("debit_amount") or 0)
        amount = credit if credit > 0 else -debit
        return BankTransaction(
            bank_ref_no=str(
                raw.get("refNo")
                or raw.get("ref_no")
                or raw.get("transactionId")
                or raw.get("transactionNumber")
            ),
            posted_at=_parse_datetime(
                str(
                    raw.get("transactionDate")
                    or raw.get("postingDate")
                    or raw.get("transactionTime")
                )
            ),
            amount=amount,
            content=str(raw.get("description") or raw.get("content") or ""),
            counter_account=_optional_str(
                raw.get("benAccountNo")
                or raw.get("counterAccount")
                or raw.get("toAccountNumber")
            ),
            counter_name=_optional_str(
                raw.get("benAccountName")
                or raw.get("counterName")
                or raw.get("toAccountName")
            ),
            raw=raw,
        )


def _to_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    if hasattr(item, "model_dump"):
        return item.model_dump()  # type: ignore[no-any-return]
    if hasattr(item, "dict"):
        return item.dict()  # type: ignore[no-any-return]
    return {key: getattr(item, key) for key in dir(item) if not key.startswith("_")}


def _parse_amount(value: Any) -> Decimal:
    normalized = str(value).replace(",", "").strip()
    if not normalized:
        return Decimal("0")
    return Decimal(normalized)


def _parse_datetime(value: str) -> datetime:
    if not value:
        return datetime.now(UTC)
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%d%m%Y%H%M%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value).astimezone(UTC)
    except ValueError:
        return datetime.now(UTC)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
