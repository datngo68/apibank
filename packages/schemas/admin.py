"""Schemas cho /api/v1/admin/*."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

# -- Users -----------------------------------------------------------------


class AdminUserListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: str | None
    role: str
    status: str
    balance_vnd: Decimal
    last_login_at: datetime | None
    created_at: datetime


class AdminUserListResponse(BaseModel):
    items: list[AdminUserListItem]
    total: int
    limit: int
    offset: int


class AdminUserDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: str | None
    role: str
    status: str
    balance_vnd: Decimal
    locale: str
    has_2fa: bool
    email_verified_at: datetime | None
    telegram_chat_id: str | None
    last_login_at: datetime | None
    created_at: datetime
    bank_accounts_count: int
    sessions_count: int
    api_keys_count: int = 0
    subscription: dict[str, Any] | None
    recent_wallet_tx: list[dict[str, Any]]
    recent_api_keys: list[dict[str, Any]] = Field(default_factory=list)


class AdminUserUpdate(BaseModel):
    role: str | None = Field(default=None, pattern="^(user|admin|owner)$")
    status: str | None = Field(default=None, pattern="^(active|suspended|banned)$")
    full_name: str | None = Field(default=None, max_length=255)
    admin_role_extra: str | None = Field(
        default=None,
        pattern="^(super_admin|support|finance|read_only)$",
    )


class WalletOpRequest(BaseModel):
    amount_vnd: int = Field(
        ..., description="VND signed; (+) cho credit/refund/adjust+, (-) cho adjust-"
    )
    note: str = Field(default="", max_length=500)
    ref_id: str | None = None


class WalletOpResponse(BaseModel):
    tx_id: str
    balance_after: Decimal
    amount_vnd: Decimal


# -- Plans -----------------------------------------------------------------


class AdminPlanRead(BaseModel):
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
    active: bool
    created_at: datetime


class AdminPlanCreate(BaseModel):
    code: str = Field(min_length=1, max_length=32, pattern="^[a-z0-9-]+$")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    price_vnd: int = Field(ge=0)
    duration_days: int = Field(ge=1)
    daily_quota: int = Field(ge=0, default=0)
    monthly_quota: int = Field(ge=0, default=0)
    features_json: dict[str, Any] = Field(default_factory=dict)
    sort_order: int = 0
    active: bool = True


class AdminPlanUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    price_vnd: int | None = Field(default=None, ge=0)
    duration_days: int | None = Field(default=None, ge=1)
    daily_quota: int | None = Field(default=None, ge=0)
    monthly_quota: int | None = Field(default=None, ge=0)
    features_json: dict[str, Any] | None = None
    sort_order: int | None = None
    active: bool | None = None


# -- Coupons ---------------------------------------------------------------


class AdminCouponRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    code: str
    description: str | None
    discount_type: str
    percent_off: int | None
    amount_off_vnd: Decimal | None
    max_discount_vnd: Decimal | None
    min_amount_vnd: Decimal | None
    max_redemptions: int | None
    max_per_user: int
    redeemed_count: int
    valid_from: datetime | None
    valid_until: datetime | None
    plan_codes_json: list[str]
    active: bool
    created_at: datetime
    updated_at: datetime


class AdminCouponCreate(BaseModel):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    description: str | None = Field(default=None, max_length=500)
    discount_type: str = Field(pattern="^(percent|fixed)$")
    percent_off: int | None = Field(default=None, ge=1, le=100)
    amount_off_vnd: int | None = Field(default=None, ge=1)
    max_discount_vnd: int | None = Field(default=None, ge=1)
    min_amount_vnd: int | None = Field(default=None, ge=0)
    max_redemptions: int | None = Field(default=None, ge=1)
    max_per_user: int = Field(default=1, ge=1, le=100)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    plan_codes: list[str] = Field(default_factory=list)
    active: bool = True

    @model_validator(mode="after")
    def _check_discount_fields(self) -> AdminCouponCreate:
        if self.discount_type == "percent":
            if self.percent_off is None:
                raise ValueError("percent_off bắt buộc khi discount_type=percent")
            if self.amount_off_vnd is not None:
                raise ValueError("amount_off_vnd phải để trống với discount_type=percent")
        else:  # fixed
            if self.amount_off_vnd is None:
                raise ValueError("amount_off_vnd bắt buộc khi discount_type=fixed")
            if self.percent_off is not None or self.max_discount_vnd is not None:
                raise ValueError(
                    "percent_off và max_discount_vnd phải để trống với discount_type=fixed"
                )
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_from >= self.valid_until
        ):
            raise ValueError("valid_until phải sau valid_from")
        return self


class AdminCouponUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=500)
    max_redemptions: int | None = Field(default=None, ge=1)
    max_per_user: int | None = Field(default=None, ge=1, le=100)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    plan_codes: list[str] | None = None
    active: bool | None = None


class AdminCouponRedemptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    coupon_code: str
    user_id: str
    invoice_id: str | None
    subscription_id: str | None
    plan_code: str | None
    amount_before_vnd: Decimal
    discount_vnd: Decimal
    amount_after_vnd: Decimal
    created_at: datetime


# -- Bank accounts ---------------------------------------------------------


class AdminBankAccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str | None
    user_email: str | None
    bank_code: str
    account_no: str
    account_holder: str
    status: str
    polling_enabled: bool
    polling_status: str
    is_system_account: bool
    last_poll_at: datetime | None
    last_error: str | None
    created_at: datetime


class AdminSystemBankSet(BaseModel):
    bank_account_id: str


# -- Stats -----------------------------------------------------------------


class AdminStats(BaseModel):
    users_total: int
    users_active: int
    orders_pending: int
    orders_paid_24h: int
    tx_24h: int
    wallet_total_vnd: Decimal
    subscriptions_active: int
    bank_accounts: int
    revenue_30d_vnd: Decimal = Decimal(0)
    mrr_vnd: Decimal = Decimal(0)
    api_keys_active: int = 0
    requests_24h: int = 0


class AdminAuditItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    actor: str
    action: str
    target_type: str
    target_id: str
    ip: str | None
    created_at: datetime
    after_json: dict[str, Any] | None
    before_json: dict[str, Any] | None


class AdminAuditResponse(BaseModel):
    items: list[AdminAuditItem]
    total: int
    limit: int
    offset: int


# -- Config: SMTP ----------------------------------------------------------


class SmtpConfigRead(BaseModel):
    host: str = ""
    port: int = 587
    user: str = ""
    from_addr: str = ""
    use_tls: bool = True
    enabled: bool = False
    password_set: bool = False


class SmtpConfigUpdate(BaseModel):
    host: str = Field(default="", max_length=255)
    port: int = Field(default=587, ge=1, le=65535)
    user: str = Field(default="", max_length=255)
    password: str | None = Field(default=None, max_length=255)
    from_addr: str = Field(default="", max_length=255)
    use_tls: bool = True
    enabled: bool = False


class SmtpTestRequest(BaseModel):
    to_email: EmailStr


class SmtpTestResponse(BaseModel):
    ok: bool
    error: str | None = None


# -- Config: Google OAuth --------------------------------------------------


class GoogleConfigRead(BaseModel):
    client_id: str = ""
    redirect_uri: str = ""
    enabled: bool = False
    client_secret_set: bool = False


class GoogleConfigUpdate(BaseModel):
    client_id: str = Field(default="", max_length=255)
    client_secret: str | None = Field(default=None, max_length=255)
    redirect_uri: str = Field(default="", max_length=512)
    enabled: bool = False


# -- Config: Telegram ------------------------------------------------------


class TelegramConfigRead(BaseModel):
    enabled: bool = False
    webhook_url: str = ""
    admin_chat_id: str = ""
    bot_username: str = ""
    bot_token_set: bool = False


class TelegramConfigUpdate(BaseModel):
    bot_token: str | None = Field(default=None, max_length=255)
    enabled: bool = False


class TelegramRegisterWebhookRequest(BaseModel):
    base_url: str = Field(min_length=1, max_length=512, description="Base URL có protocol, vd https://example.com")


class TelegramRegisterWebhookResponse(BaseModel):
    ok: bool
    description: str | None = None
    webhook_url: str | None = None


class TelegramLinkChatResponse(BaseModel):
    deep_link_url: str
    token: str
    expires_in: int


# -- Admin API keys --------------------------------------------------------


class AdminApiKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str | None
    user_email: str | None = None
    name: str | None
    scopes: list[str]
    last_used_at: datetime | None
    last_used_ip: str | None
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class AdminApiKeyListResponse(BaseModel):
    items: list[AdminApiKeyRead]
    total: int
    limit: int
    offset: int


class AdminApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    scopes: list[str] = Field(default_factory=lambda: ["orders:write", "orders:read"])
    expires_at: datetime | None = None


class AdminApiKeyCreated(AdminApiKeyRead):
    raw_key: str


# -- Admin usage analytics -------------------------------------------------


class AdminUsageEndpointRow(BaseModel):
    endpoint_group: str
    count: int
    error_count: int


class AdminUsageUserRow(BaseModel):
    user_id: str
    user_email: str | None = None
    count: int
    error_count: int


class AdminUsageSummary(BaseModel):
    days: int
    total_count: int
    total_errors: int
    unique_users: int
    unique_api_keys: int
    top_endpoints: list[AdminUsageEndpointRow]
    top_users: list[AdminUsageUserRow]


class AdminUsageDailyPoint(BaseModel):
    day: str  # ISO date
    count: int
    error_count: int


class AdminUsageTimeseries(BaseModel):
    days: int
    user_id: str | None = None
    api_key_id: str | None = None
    points: list[AdminUsageDailyPoint]


class AdminUsageApiKeyBreakdown(BaseModel):
    api_key_id: str
    name: str | None
    count: int
    error_count: int


class AdminUserUsageDetail(BaseModel):
    user_id: str
    days: int
    total_count: int
    total_errors: int
    points: list[AdminUsageDailyPoint]
    by_api_key: list[AdminUsageApiKeyBreakdown]
    by_endpoint: list[AdminUsageEndpointRow]


# -- Admin revenue ---------------------------------------------------------


class AdminRevenueSummary(BaseModel):
    today_vnd: Decimal
    this_month_vnd: Decimal
    last_30d_vnd: Decimal
    mrr_vnd: Decimal
    total_invoices_paid: int
    topup_vnd_30d: Decimal
    refund_vnd_30d: Decimal
    discount_vnd_30d: Decimal


class AdminRevenuePoint(BaseModel):
    day: str
    subscription_vnd: Decimal
    topup_vnd: Decimal
    refund_vnd: Decimal
    discount_vnd: Decimal
    net_vnd: Decimal


class AdminRevenueTimeseries(BaseModel):
    days: int
    points: list[AdminRevenuePoint]


class AdminRevenueByPlanRow(BaseModel):
    plan_code: str | None
    invoices: int
    gross_vnd: Decimal
    discount_vnd: Decimal
    net_vnd: Decimal


class AdminRevenueByCouponRow(BaseModel):
    coupon_code: str | None
    redemptions: int
    discount_vnd: Decimal
    net_vnd: Decimal


class AdminInvoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    user_email: str | None = None
    plan_code: str | None
    amount_vnd: Decimal
    currency: str
    status: str
    coupon_code: str | None = None
    discount_vnd: Decimal = Decimal(0)
    original_amount_vnd: Decimal | None = None
    issued_at: datetime


class AdminInvoiceListResponse(BaseModel):
    items: list[AdminInvoiceRead]
    total: int
    limit: int
    offset: int
