"""Schemas cho /api/v1/admin/*."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

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
    subscription: dict[str, Any] | None
    recent_wallet_tx: list[dict[str, Any]]


class AdminUserUpdate(BaseModel):
    role: str | None = Field(default=None, pattern="^(user|admin|owner)$")
    status: str | None = Field(default=None, pattern="^(active|suspended|banned)$")
    full_name: str | None = Field(default=None, max_length=255)


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
