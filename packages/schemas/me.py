"""Schemas cho /api/v1/me/* và /api/v1/plans."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

# -- Bank accounts ----------------------------------------------------------


class BankAccountCreate(BaseModel):
    bank_code: str = Field(min_length=2, max_length=16)
    account_no: str = Field(min_length=6, max_length=64)
    account_holder: str = Field(min_length=1, max_length=255)
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=255)


class BankAccountRotate(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=255)


class BankAccountUpdate(BaseModel):
    """Toggle polling tạm thời (pause khi user chuyển tiền trên app mobile)."""

    polling_enabled: bool


class BankAccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    bank_code: str
    account_no: str
    account_holder: str
    status: str
    polling_enabled: bool
    polling_status: str
    last_login_at: datetime | None
    last_poll_at: datetime | None
    verified_at: datetime | None
    last_error: str | None
    is_system_account: bool
    created_at: datetime


# -- Webhooks ---------------------------------------------------------------


class MeWebhookCreate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    url: HttpUrl
    secret: str = Field(min_length=16, max_length=128)
    active: bool = True
    headers: dict[str, str] = Field(default_factory=dict)
    events: list[str] = Field(default_factory=list)


class MeWebhookUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    active: bool | None = None
    events: list[str] | None = None


class MeWebhookRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str | None
    url: str
    active: bool
    events_json: dict[str, Any]
    headers_json: dict[str, Any]
    last_delivery_at: datetime | None
    created_at: datetime


# -- API keys ---------------------------------------------------------------


class MeApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    scopes: list[str] = Field(default_factory=lambda: ["orders:write", "orders:read"])
    expires_at: datetime | None = None


class MeApiKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str | None
    scopes: list[str]
    last_used_at: datetime | None
    last_used_ip: str | None
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class MeApiKeyCreated(MeApiKeyRead):
    raw_key: str


# -- Wallet -----------------------------------------------------------------


class WalletBalanceRead(BaseModel):
    balance_vnd: Decimal
    pending_topups: int = 0


class WalletTransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    amount_vnd: Decimal
    balance_after: Decimal
    ref_kind: str | None
    ref_id: str | None
    note: str | None
    created_at: datetime


class TopupCreateRequest(BaseModel):
    amount_vnd: int = Field(ge=2_000, le=50_000_000)


class TopupResponse(BaseModel):
    order_id: str
    code: str
    amount_vnd: Decimal
    status: str
    expired_at: datetime
    pay_url: str
    qr_url: str
    bank_code: str
    bank_name: str
    account_no: str
    account_holder: str
    transfer_content: str


class TopupListItem(BaseModel):
    """Đơn nạp ví đang chờ — đủ data để render lại dialog QR."""

    order_id: str
    code: str
    amount_vnd: Decimal
    status: str
    created_at: datetime
    expired_at: datetime
    pay_url: str
    qr_url: str
    bank_code: str
    bank_name: str
    account_no: str
    account_holder: str
    transfer_content: str


class TopupCheckResponse(BaseModel):
    """Kết quả của nút "Tôi đã chuyển khoản" — force-check 1 đơn topup.

    - ``status``: trạng thái mới nhất sau khi đã kick poll worker và đợi
      tối đa ``waited_ms`` ms. Có thể là ``pending`` (chưa thấy giao dịch),
      ``paid`` (đã match + credit ví) hoặc ``expired/canceled``.
    - ``balance_vnd``: số dư ví sau credit, chỉ có khi ``status="paid"``.
    - ``waited_ms``: BE thực sự đã đợi bao lâu (FE dùng để hiển thị toast).
    - ``message``: text gợi ý tiếng Việt cho FE hiển thị nhanh.
    """

    order_id: str
    code: str
    status: str
    balance_vnd: Decimal | None = None
    waited_ms: int = 0
    message: str


# -- Subscription / Plans ---------------------------------------------------


class PlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    code: str
    name: str
    description: str | None
    price_vnd: Decimal
    duration_days: int
    daily_quota: int
    monthly_quota: int
    features_json: dict[str, Any]
    sort_order: int


class SubscriptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    plan_id: str
    plan_code: str | None = None
    started_at: datetime
    expires_at: datetime
    status: str
    auto_renew: bool


class SubscriptionPurchaseRequest(BaseModel):
    plan_code: str = Field(min_length=1, max_length=32)
    coupon_code: str | None = Field(default=None, max_length=64)


class CouponPreviewRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    plan_code: str = Field(min_length=1, max_length=32)


class CouponPreviewResponse(BaseModel):
    code: str
    plan_code: str
    discount_type: str
    original_amount_vnd: Decimal
    discount_vnd: Decimal
    final_amount_vnd: Decimal


class InvoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    plan_code: str | None
    amount_vnd: Decimal
    currency: str
    status: str
    issued_at: datetime
    coupon_code: str | None = None
    discount_vnd: Decimal = Decimal(0)
    original_amount_vnd: Decimal | None = None


# -- Orders / Transactions list ---------------------------------------------


class OrderListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    code: str
    amount_vnd: Decimal
    status: str
    bank_account_id: str
    description: str | None
    customer_ref: str | None
    expired_at: datetime
    paid_at: datetime | None
    created_at: datetime


class TransactionListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    bank_account_id: str
    bank_ref_no: str
    amount_vnd: Decimal
    content: str
    state: str
    matched_order_id: str | None
    posted_at: datetime


# -- Notifications (in-app inbox) ------------------------------------------


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    title: str
    body: str | None
    payload_json: dict[str, Any]
    read_at: datetime | None
    created_at: datetime


class NotificationUnreadCount(BaseModel):
    unread: int


# -- Notification preferences (matrix kind x channel) ----------------------

VALID_NOTIFICATION_CHANNELS = ("in_app", "email", "telegram")


class NotificationPreferenceItem(BaseModel):
    """Một dòng matrix: với `kind` này, kênh `channel` có bật hay không."""

    model_config = ConfigDict(from_attributes=True)

    kind: str
    channel: str
    enabled: bool


class NotificationPreferenceList(BaseModel):
    """Trả về toàn bộ matrix prefs để FE render bảng."""

    items: list[NotificationPreferenceItem]


class NotificationPreferenceUpdateItem(BaseModel):
    kind: str
    channel: str
    enabled: bool


class NotificationPreferenceUpdate(BaseModel):
    """Bulk upsert matrix prefs."""

    items: list[NotificationPreferenceUpdateItem]
