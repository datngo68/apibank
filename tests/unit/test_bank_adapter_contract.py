import json
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from packages.banks.base import BankTransaction
from packages.banks.mb.adapter import MBAdapter
from packages.banks.registry import restore_adapter_session, serialize_adapter_session
from packages.security.crypto import FernetCipher


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


class _FakeOCR:
    def process_image(self, _image: bytes) -> str:
        return "ABCD"


class _FakeLoginClient:
    def __init__(self, *, session_id: str | None = None) -> None:
        self.sessionId = session_id
        self.login_calls = 0
        self.captcha_calls = 0

    async def get_capcha_image(self) -> bytes:
        self.captcha_calls += 1
        return b"captcha"

    async def login(self, _captcha: str) -> None:
        self.login_calls += 1
        self.sessionId = "new-session"


@pytest.mark.asyncio
async def test_mb_login_reuses_existing_session() -> None:
    adapter = MBAdapter(username="u", password="p")
    fake = _FakeLoginClient(session_id="active-session")
    adapter._client = fake  # type: ignore[assignment]
    adapter._ocr = _FakeOCR()  # type: ignore[assignment]

    await adapter.login()

    assert fake.captcha_calls == 0
    assert fake.login_calls == 0
    assert fake.sessionId == "active-session"


def test_mb_session_state_round_trip() -> None:
    adapter = MBAdapter(username="u", password="p")
    fake = _FakeLoginClient(session_id="active-session")
    fake.deviceIdCommon = "device-1"  # type: ignore[attr-defined]
    fake._userinfo = {"cust": {"id": "customer-1"}}  # type: ignore[attr-defined]
    adapter._client = fake  # type: ignore[assignment]

    state = adapter.export_session()

    restored = MBAdapter(username="u", password="p")
    restored_fake = _FakeLoginClient()
    restored_fake.deviceIdCommon = "new-device"  # type: ignore[attr-defined]
    restored_fake._userinfo = None  # type: ignore[attr-defined]
    restored._client = restored_fake  # type: ignore[assignment]
    restored.restore_session(json.loads(json.dumps(state)))

    assert restored_fake.sessionId == "active-session"
    assert restored_fake.deviceIdCommon == "device-1"  # type: ignore[attr-defined]
    assert restored_fake._userinfo == {"cust": {"id": "customer-1"}}  # type: ignore[attr-defined]


def test_mb_session_storage_is_encrypted() -> None:
    cipher = FernetCipher.from_keys(f"primary:{FernetCipher.generate_key()}")
    adapter = MBAdapter(username="u", password="p")
    fake = _FakeLoginClient(session_id="secret-session")
    fake.deviceIdCommon = "device-1"  # type: ignore[attr-defined]
    fake._userinfo = {"customer": "secret-user"}  # type: ignore[attr-defined]
    adapter._client = fake  # type: ignore[assignment]

    encrypted = serialize_adapter_session(adapter, cipher=cipher)

    assert encrypted is not None
    assert "secret-session" not in encrypted

    restored = MBAdapter(username="u", password="p")
    restored_fake = _FakeLoginClient()
    restored_fake.deviceIdCommon = "new-device"  # type: ignore[attr-defined]
    restored_fake._userinfo = None  # type: ignore[attr-defined]
    restored._client = restored_fake  # type: ignore[assignment]
    assert restore_adapter_session(restored, encrypted, cipher=cipher) is True
    assert restored_fake.sessionId == "secret-session"


def test_invalid_mb_session_storage_is_ignored() -> None:
    cipher = FernetCipher.from_keys(f"primary:{FernetCipher.generate_key()}")
    adapter = MBAdapter(username="u", password="p")

    assert restore_adapter_session(adapter, "not-a-fernet-token", cipher=cipher) is False
    assert adapter._client is None


@pytest.mark.asyncio
async def test_mb_login_authenticates_when_session_is_missing() -> None:
    adapter = MBAdapter(username="u", password="p")
    fake = _FakeLoginClient()
    adapter._client = fake  # type: ignore[assignment]
    adapter._ocr = _FakeOCR()  # type: ignore[assignment]

    await adapter.login()

    assert fake.captcha_calls == 1
    assert fake.login_calls == 1
    assert fake.sessionId == "new-session"


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
