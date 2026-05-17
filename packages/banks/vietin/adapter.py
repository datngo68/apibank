"""VietinBank iPay adapter — reverse-engineered scaffold.

Adapter này là khung sẵn sàng cho việc reverse-engineer
`ipay.vietinbank.vn`. Hiện chưa có thư viện Python nào (đã tra PyPI +
GitHub vào 2026-05). Reference duy nhất là repo JS
`intagaming/actualbudget-vietinbank` chỉ paste manual JSON từ DevTools.

## Cần có gì để hoàn thiện adapter này

1. **Login flow**: VietinBank dùng OAuth-like 2 bước
   - POST `/api/login/captcha` → trả captcha image (hoặc bypass nếu device
     đã đăng ký)
   - POST `/api/login/authenticate` → trả `access_token` + `refresh_token`
   Cần capture từ DevTools (Network tab khi login thật) để biết:
   - URL endpoint chính xác
   - Header bắt buộc (X-CIF, X-DeviceId, User-Agent, Authorization, ...)
   - Body schema (có ký HMAC/JWT không?)
   - Cách lib JS sinh `deviceId` / `cifNo`

2. **Transaction history**: POST `/api/getHistTransactions`
   - Body có chứa `accountNo`, `fromDate`, `toDate` (thử cả `dd/MM/yyyy`
     và `yyyy-MM-dd`)
   - Response `getHistTransactions` trả array, schema có thể:
     ```json
     {"transactions": [{"refNo": "...", "transDate": "...",
                        "creditAmount": "...", "debitAmount": "...",
                        "description": "..."}]}
     ```

3. **Session refresh**: nếu `access_token` hết hạn → refresh hoặc relogin

## Cách lấy nguyên liệu (User-side)

1. Login `https://ipay.vietinbank.vn/login`
2. Mở DevTools (F12) → tab Network → tick "Preserve log"
3. Vào tab Lịch sử giao dịch → chọn 1 tài khoản → xem giao dịch
4. Filter `getHistTransactions` (hoặc `transactions`, `history`)
5. Right-click request → Copy → "Copy as cURL (bash)"
6. Paste vào file `private_research/vietin_capture.txt` (gitignore)
7. Cũng copy luôn `getCaptchaImage` + `authenticate` từ lúc login

Khi có file đó, mình sẽ điền đúng URL/header/body vào skeleton này.

## Tại sao không paste sẵn URL phỏng đoán

Adapter cần đúng tới từng header. Nếu mình hardcode URL từ blog spam thì
khi VietinBank đổi version (rất hay xảy ra) sẽ fail âm thầm. Capture từ
DevTools là cách duy nhất chắc chắn.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from packages.banks.base import BankAuthError, BankError, BankRateLimited, BankTransaction

_VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

# TODO(reverse-engineer): replace với endpoint thật từ DevTools capture
_BASE_URL = "https://ipay.vietinbank.vn"
_LOGIN_PATH = "/login/api/v1/authenticate"  # placeholder, cần verify
_HISTORY_PATH = "/transactions/api/v1/getHistTransactions"  # placeholder


class VietinAdapter:
    bank_code = "VTB"

    def __init__(
        self,
        *,
        username: str,
        password: str,
        device_id: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        self._username = username
        self._password = password
        self._device_id = device_id or _derive_device_id(username)
        self._timeout = timeout
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._client: httpx.AsyncClient | None = None

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=_BASE_URL,
                timeout=self._timeout,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0 Safari/537.36"
                    ),
                    "Accept": "application/json, text/plain, */*",
                    "Origin": _BASE_URL,
                    "Referer": f"{_BASE_URL}/login",
                },
            )
        return self._client

    async def login(self) -> None:
        """Login + lưu access_token.

        TODO(reverse-engineer): điền body/headers chính xác sau khi capture
        DevTools. Hiện raise NotImplementedError để tránh gọi thật mà fail
        âm thầm.
        """
        raise NotImplementedError(
            "VietinBank login chưa hoàn thiện. Xem docstring file này, "
            "capture DevTools và điền vào _do_login_request()."
        )

    async def _do_login_request(self, captcha_text: str | None = None) -> dict[str, Any]:
        """Gọi endpoint authenticate. Tách riêng để dễ test."""
        client = self._ensure_client()
        # TODO(reverse-engineer): điền payload & header thật
        payload: dict[str, Any] = {
            "username": self._username,
            "password": self._password,
            "deviceId": self._device_id,
        }
        if captcha_text:
            payload["captcha"] = captcha_text
        try:
            response = await client.post(_LOGIN_PATH, json=payload)
        except httpx.HTTPError as exc:
            raise BankAuthError(f"vietin login transport: {exc!r}") from exc
        if response.status_code == 429:
            raise BankRateLimited(f"vietin login rate-limited: {response.text}")
        if response.status_code >= 400:
            raise BankAuthError(
                f"vietin login http {response.status_code}: {response.text[:200]}"
            )
        return response.json()

    async def health(self) -> bool:
        return self._access_token is not None

    async def get_balance(self, account_no: str) -> Decimal:
        # TODO(reverse-engineer): cần endpoint balance nếu cần dùng
        raise NotImplementedError("VietinAdapter.get_balance chưa hỗ trợ")

    async def list_transactions(
        self, account_no: str, start: datetime, end: datetime
    ) -> AsyncIterator[BankTransaction]:
        if self._access_token is None:
            await self.login()
        # VietinBank lọc theo giờ VN giống MB → convert trước khi format.
        start_vn = (start.astimezone(_VN_TZ) if start.tzinfo
                    else start.replace(tzinfo=UTC).astimezone(_VN_TZ))
        end_vn = (end.astimezone(_VN_TZ) if end.tzinfo
                  else end.replace(tzinfo=UTC).astimezone(_VN_TZ))

        client = self._ensure_client()
        # TODO(reverse-engineer): body & header chính xác
        payload = {
            "accountNo": account_no,
            "fromDate": start_vn.strftime("%d/%m/%Y"),
            "toDate": end_vn.strftime("%d/%m/%Y"),
        }
        headers = {"Authorization": f"Bearer {self._access_token}"}
        try:
            resp = await client.post(_HISTORY_PATH, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise BankError(f"vietin history transport: {exc!r}") from exc
        if resp.status_code == 401:
            self._access_token = None
            raise BankAuthError("vietin token expired")
        if resp.status_code == 429:
            raise BankRateLimited("vietin history rate-limited")
        if resp.status_code >= 400:
            raise BankError(
                f"vietin history http {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json()
        for raw in _extract_items(data):
            yield map_vietin_transaction(raw)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def _derive_device_id(username: str) -> str:
    """Sinh deviceId ổn định từ username để VietinBank không yêu cầu OTP
    đăng ký device mỗi lần login. Real lib có thể dùng UUID + lưu trong
    localStorage; đây là fallback đơn giản, đủ deterministic.
    """
    import hashlib

    return hashlib.sha256(f"apibank-{username}".encode()).hexdigest()[:32]


def _extract_items(data: Any) -> list[dict[str, Any]]:
    """VietinBank đôi khi bọc array trong nhiều layer khác nhau qua các
    version. Thử các shape phổ biến."""
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("transactions", "transactionList", "data", "items", "result"):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            inner = _extract_items(value)
            if inner:
                return inner
    return []


def map_vietin_transaction(raw: dict[str, Any]) -> BankTransaction:
    """Map raw dict từ VietinBank API sang BankTransaction.

    Tách hàm riêng để unit test không cần network.
    """
    credit = _parse_amount(raw.get("creditAmount") or raw.get("creditAmt") or 0)
    debit = _parse_amount(raw.get("debitAmount") or raw.get("debitAmt") or 0)
    amount = credit if credit > 0 else -debit

    return BankTransaction(
        bank_ref_no=str(
            raw.get("refNo")
            or raw.get("transactionRef")
            or raw.get("ref")
            or raw.get("id")
        ),
        posted_at=_parse_datetime(
            str(
                raw.get("transDate")
                or raw.get("transactionDate")
                or raw.get("postingDate")
                or ""
            )
        ),
        amount=amount,
        content=str(raw.get("description") or raw.get("remark") or raw.get("memo") or ""),
        counter_account=_optional_str(
            raw.get("counterAccount") or raw.get("benAccountNo")
        ),
        counter_name=_optional_str(
            raw.get("counterName") or raw.get("benAccountName")
        ),
        raw=raw,
    )


def _parse_amount(value: Any) -> Decimal:
    text = str(value).replace(",", "").replace(" ", "").strip()
    if not text:
        return Decimal("0")
    try:
        return Decimal(text)
    except Exception:  # noqa: BLE001
        return Decimal("0")


def _parse_datetime(value: str) -> datetime:
    if not value:
        return datetime.now(UTC)
    for fmt in (
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=_VN_TZ).astimezone(UTC)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value).astimezone(UTC)
    except (ValueError, TypeError):
        return datetime.now(UTC)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
