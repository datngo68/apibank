from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from packages.banks.base import BankTransaction
from packages.banks.mb.adapter import MBAdapter


def test_bank_transaction_amount_must_not_be_zero() -> None:
    with pytest.raises(ValueError, match="amount must be non-zero"):
        BankTransaction(
            bank_ref_no="FT1",
            posted_at=datetime.now(UTC),
            amount=Decimal("0"),
            content="PAY DH123456",
            counter_account=None,
            counter_name=None,
            raw={},
        )


def test_mb_adapter_maps_raw_transaction_to_bank_transaction() -> None:
    adapter = MBAdapter(username="u", password="p")
    raw = {
        "refNo": "FT123",
        "transactionDate": "16/05/2026 10:30:01",
        "creditAmount": "150,000",
        "debitAmount": "0",
        "description": "NAP TIEN DH123456",
        "benAccountNo": "0123456789",
        "benAccountName": "NGUYEN VAN A",
    }

    tx = adapter.map_transaction(raw)

    assert tx.bank_ref_no == "FT123"
    assert tx.amount == Decimal("150000")
    assert tx.content == "NAP TIEN DH123456"
    assert tx.counter_account == "0123456789"
    assert tx.counter_name == "NGUYEN VAN A"
    assert tx.posted_at == datetime(2026, 5, 16, 10, 30, 1, tzinfo=UTC)


class _FakeMBClient:
    """Stub MBBankAsync — chỉ ghi nhận tham số được truyền vào."""

    def __init__(self) -> None:
        self.sessionId = "stub-session"
        self.captured: dict[str, datetime] = {}

    async def getTransactionAccountHistory(
        self, *, accountNo: str, from_date: datetime, to_date: datetime
    ):
        self.captured["accountNo"] = accountNo  # type: ignore[assignment]
        self.captured["from_date"] = from_date
        self.captured["to_date"] = to_date

        class _Result:
            transactionHistoryList: list = []

        return _Result()


@pytest.mark.asyncio
async def test_mb_list_transactions_converts_window_to_vn_tz() -> None:
    """Regression: trước fix, end=18:30 UTC ngày 16/05 -> strftime ra 16/05,
    bỏ sót giao dịch ngày 17/05 (giờ VN). Sau fix, lib phải nhận giờ VN."""
    adapter = MBAdapter(username="u", password="p")
    fake = _FakeMBClient()
    adapter._client = fake  # type: ignore[assignment]

    start = datetime(2026, 5, 15, 18, 30, tzinfo=UTC)
    end = datetime(2026, 5, 16, 18, 30, tzinfo=UTC)
    async for _ in adapter.list_transactions("368682001", start, end):
        pass

    vn = ZoneInfo("Asia/Ho_Chi_Minh")
    assert fake.captured["from_date"] == start.astimezone(vn)
    assert fake.captured["to_date"] == end.astimezone(vn)
    # Sau khi convert: end=01:30 +07 ngày 17/05 -> strftime "17/05/2026"
    assert fake.captured["to_date"].strftime("%d/%m/%Y") == "17/05/2026"
    assert fake.captured["from_date"].strftime("%d/%m/%Y") == "16/05/2026"


@pytest.mark.asyncio
async def test_mb_list_transactions_treats_naive_datetime_as_utc() -> None:
    """Worker đôi khi load datetime naive từ DB. Adapter phải coi như UTC."""
    adapter = MBAdapter(username="u", password="p")
    fake = _FakeMBClient()
    adapter._client = fake  # type: ignore[assignment]

    naive_start = datetime(2026, 5, 15, 18, 0)  # = 16/05 01:00 +07
    naive_end = datetime(2026, 5, 16, 18, 0)  # = 17/05 01:00 +07
    async for _ in adapter.list_transactions("368682001", naive_start, naive_end):
        pass

    assert fake.captured["from_date"].strftime("%d/%m/%Y") == "16/05/2026"
    assert fake.captured["to_date"].strftime("%d/%m/%Y") == "17/05/2026"
