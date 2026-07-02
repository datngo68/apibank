from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from datetime import date as _date_t
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    # Map mọi `Mapped[datetime]` (và Optional) sang TIMESTAMP WITH TIME ZONE.
    # Lý do: code dùng `datetime.now(UTC)` (tz-aware), Postgres strict yêu
    # cầu cột TIMESTAMPTZ; SQLite không có timezone, fallback an toàn.
    # Nếu không khai báo, SQLAlchemy tạo TIMESTAMP WITHOUT TIME ZONE →
    # asyncpg reject "can't subtract offset-naive and offset-aware datetimes".
    type_annotation_map = {
        dict[str, Any]: JSON,
        datetime: DateTime(timezone=True),
    }


class BankAccount(Base):
    __tablename__ = "bank_accounts"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"ba_{secrets.token_urlsafe(16)}"
    )
    user_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.id"), nullable=True, index=True
    )
    bank_code: Mapped[str] = mapped_column(String(16), index=True)
    account_no: Mapped[str] = mapped_column(String(64), index=True)
    account_holder: Mapped[str] = mapped_column(String(255))
    credentials_enc: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    is_system_account: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None]
    last_poll_at: Mapped[datetime | None]
    polling_enabled: Mapped[bool] = mapped_column(default=True)
    polling_status: Mapped[str] = mapped_column(String(16), default="idle")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"ord_{secrets.token_urlsafe(16)}"
    )
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    amount_vnd: Mapped[Decimal] = mapped_column(Numeric(18, 0))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    bank_account_id: Mapped[str] = mapped_column(ForeignKey("bank_accounts.id"), index=True)
    # Denormalized owner cho topup orders để tránh đọc metadata_json + scan
    # theo customer_ref (string match trên email). NULL cho order thường tạo
    # qua POST /v1/orders (chỉ có api_key, không gắn user trực tiếp).
    user_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.id"), nullable=True, index=True
    )
    expired_at: Mapped[datetime] = mapped_column(index=True)
    paid_tx_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("transactions.id"), nullable=True
    )
    paid_at: Mapped[datetime | None]
    customer_ref: Mapped[str | None] = mapped_column(String(255))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    paid_transaction: Mapped[Transaction | None] = relationship(
        "Transaction", foreign_keys="Order.paid_tx_id", post_update=True
    )

    @classmethod
    def new(
        cls,
        *,
        amount_vnd: Decimal,
        bank_account_id: str,
        ttl_seconds: int,
        description: str | None = None,
        customer_ref: str | None = None,
        metadata_json: dict[str, Any] | None = None,
        user_id: str | None = None,
    ) -> Order:
        return cls(
            code=_generate_order_code(),
            amount_vnd=amount_vnd,
            bank_account_id=bank_account_id,
            description=description,
            customer_ref=customer_ref,
            status="pending",
            user_id=user_id,
            metadata_json=metadata_json or {},
            expired_at=utcnow() + timedelta(seconds=ttl_seconds),
        )


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("bank_account_id", "bank_ref_no", name="uq_transaction_bank_ref"),
    )

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"tx_{secrets.token_urlsafe(16)}"
    )
    bank_account_id: Mapped[str] = mapped_column(ForeignKey("bank_accounts.id"), index=True)
    bank_ref_no: Mapped[str] = mapped_column(String(128), index=True)
    amount_vnd: Mapped[Decimal] = mapped_column(Numeric(18, 0))
    content: Mapped[str] = mapped_column(Text)
    posted_at: Mapped[datetime] = mapped_column(index=True)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    matched_order_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("orders.id"), nullable=True
    )
    state: Mapped[str] = mapped_column(String(32), default="new", index=True)
    inserted_at: Mapped[datetime] = mapped_column(default=utcnow)


class Webhook(Base):
    __tablename__ = "webhooks"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"wh_{secrets.token_urlsafe(16)}"
    )
    owner_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    user_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.id"), nullable=True, index=True
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str] = mapped_column(Text)
    secret_enc: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(default=True)
    headers_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    events_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ip_allowlist: Mapped[str | None] = mapped_column(Text)
    last_delivery_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class WebhookAttempt(Base):
    __tablename__ = "webhook_attempts"
    __table_args__ = (
        # Hot-path query "lấy attempt due" trong dispatcher dùng đồng thời
        # status + next_run_at. Composite index giúp atomic claim với
        # SKIP LOCKED nhanh hơn so với 2 single-column index.
        Index("ix_webhook_attempts_status_next", "status", "next_run_at"),
    )

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"evt_{secrets.token_urlsafe(16)}"
    )
    webhook_id: Mapped[str] = mapped_column(ForeignKey("webhooks.id"), index=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    transaction_id: Mapped[str] = mapped_column(ForeignKey("transactions.id"), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    signature: Mapped[str | None] = mapped_column(Text)
    attempt: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=7)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    next_run_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    # claimed_at: thời điểm dispatcher claim row (status='dispatching').
    # Nếu vẫn 'dispatching' và claimed_at < now-5min → coi như crash giữa,
    # cleanup job reset về 'pending'.
    claimed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_status_code: Mapped[int | None]
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None]

    webhook: Mapped[Webhook] = relationship("Webhook", lazy="raise")

    @classmethod
    def new(
        cls,
        *,
        webhook_id: str,
        order_id: str,
        transaction_id: str,
        payload: dict[str, Any],
    ) -> WebhookAttempt:
        return cls(
            webhook_id=webhook_id,
            order_id=order_id,
            transaction_id=transaction_id,
            payload=payload,
            max_attempts=7,
            status="pending",
            attempt=0,
        )


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"ak_{secrets.token_urlsafe(16)}"
    )
    owner_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    user_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.id"), nullable=True, index=True
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    key_hash: Mapped[str] = mapped_column(String(128), unique=True)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    # IP allowlist per key (CIDR list). Empty list = không giới hạn.
    ip_allowlist_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Mode: live | test (test mode không charge thật, chỉ dùng cho integration test).
    mode: Mapped[str] = mapped_column(String(8), default="live")
    last_used_at: Mapped[datetime | None]
    last_used_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    revoked_at: Mapped[datetime | None]


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("api_key_id", "key", name="uq_idempotency_api_key"),)

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"idem_{secrets.token_urlsafe(16)}"
    )
    key: Mapped[str] = mapped_column(String(255))
    api_key_id: Mapped[str] = mapped_column(ForeignKey("api_keys.id"), index=True)
    request_hash: Mapped[str] = mapped_column(String(128))
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(index=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"audit_{secrets.token_urlsafe(16)}"
    )
    actor: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(255), index=True)
    target_type: Mapped[str] = mapped_column(String(255))
    target_id: Mapped[str] = mapped_column(String(255), index=True)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(Text)
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class PollCursor(Base):
    __tablename__ = "poll_cursors"

    bank_account_id: Mapped[str] = mapped_column(
        ForeignKey("bank_accounts.id"), primary_key=True
    )
    last_seen_at: Mapped[datetime | None]
    last_ref_no: Mapped[str | None] = mapped_column(String(128))
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


# ---------------------------------------------------------------------------
# SaaS user, billing and ops models (Phase 1+2)
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"usr_{secrets.token_urlsafe(16)}"
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email_verified_at: Mapped[datetime | None]
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(16), default="user", index=True)
    # Sub-role cho admin tier (super_admin|support|finance|read_only). NULL
    # = legacy: admin/owner mặc định 'super_admin'. Xem `packages.security.permissions`.
    admin_role_extra: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    balance_vnd: Mapped[Decimal] = mapped_column(Numeric(18, 0), default=Decimal(0))
    locale: Mapped[str] = mapped_column(String(8), default="vi")
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Email cho hoá đơn/tax (tách khỏi login email).
    billing_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_login_at: Mapped[datetime | None]
    failed_login_count: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None]


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"sess_{secrets.token_urlsafe(16)}"
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(index=True)
    revoked_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class EmailToken(Base):
    __tablename__ = "email_tokens"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"emt_{secrets.token_urlsafe(16)}"
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(index=True)
    used_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class TwoFactor(Base):
    __tablename__ = "two_factors"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    secret_enc: Mapped[str] = mapped_column(Text)
    recovery_codes_enc: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled_at: Mapped[datetime | None]
    last_totp_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    last_totp_used_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class OAuthIdentity(Base):
    __tablename__ = "oauth_identities"
    __table_args__ = (
        UniqueConstraint("provider", "subject", name="uq_oauth_provider_subject"),
    )

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"oid_{secrets.token_urlsafe(16)}"
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    subject: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"plan_{secrets.token_urlsafe(12)}"
    )
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_vnd: Mapped[Decimal] = mapped_column(Numeric(18, 0))
    duration_days: Mapped[int] = mapped_column()
    daily_quota: Mapped[int] = mapped_column(default=0)
    monthly_quota: Mapped[int] = mapped_column(default=0)
    features_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    sort_order: Mapped[int] = mapped_column(default=0)
    active: Mapped[bool] = mapped_column(default=True)
    # Plan đã archive — ẩn khỏi pricing page nhưng giữ để invoice cũ vẫn ref được.
    archived_at: Mapped[datetime | None]
    # Khi gắn experiment_key, FE/admin có thể track conversion riêng.
    experiment_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"sub_{secrets.token_urlsafe(16)}"
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    auto_renew: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"inv_{secrets.token_urlsafe(16)}"
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    subscription_id: Mapped[str | None] = mapped_column(
        ForeignKey("subscriptions.id"), nullable=True
    )
    plan_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    amount_vnd: Mapped[Decimal] = mapped_column(Numeric(18, 0))
    currency: Mapped[str] = mapped_column(String(8), default="VND")
    status: Mapped[str] = mapped_column(String(16), default="paid", index=True)
    wallet_tx_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    coupon_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    discount_vnd: Mapped[Decimal] = mapped_column(Numeric(18, 0), default=Decimal(0))
    original_amount_vnd: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 0), nullable=True
    )


class Coupon(Base):
    """Mã giảm giá áp dụng khi mua/đổi subscription.

    - `discount_type`: 'percent' (`percent_off` 1..100) hoặc 'fixed'
      (`amount_off_vnd`).
    - `max_discount_vnd`: trần discount khi `percent` (NULL = không trần).
    - `plan_codes_json`: list plan_code áp dụng; rỗng/None → mọi plan.
    - `redeemed_count` increment có guard `< max_redemptions` để tránh race.
    """

    __tablename__ = "coupons"
    __table_args__ = (
        UniqueConstraint("code", name="uq_coupons_code"),
    )

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"cpn_{secrets.token_urlsafe(12)}"
    )
    code: Mapped[str] = mapped_column(String(64), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    discount_type: Mapped[str] = mapped_column(String(16))  # percent | fixed
    percent_off: Mapped[int | None] = mapped_column(nullable=True)
    amount_off_vnd: Mapped[Decimal | None] = mapped_column(Numeric(18, 0), nullable=True)
    max_discount_vnd: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 0), nullable=True
    )
    min_amount_vnd: Mapped[Decimal | None] = mapped_column(Numeric(18, 0), nullable=True)
    max_redemptions: Mapped[int | None] = mapped_column(nullable=True)
    max_per_user: Mapped[int] = mapped_column(default=1)
    redeemed_count: Mapped[int] = mapped_column(default=0)
    valid_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    plan_codes_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(default=True, index=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class CouponRedemption(Base):
    """Audit trail: mỗi lần một user redeem coupon thành công."""

    __tablename__ = "coupon_redemptions"
    __table_args__ = (
        Index("ix_coupon_redemptions_coupon_user", "coupon_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"crd_{secrets.token_urlsafe(12)}"
    )
    coupon_id: Mapped[str] = mapped_column(ForeignKey("coupons.id"), index=True)
    coupon_code: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    invoice_id: Mapped[str | None] = mapped_column(
        ForeignKey("invoices.id"), nullable=True
    )
    subscription_id: Mapped[str | None] = mapped_column(
        ForeignKey("subscriptions.id"), nullable=True
    )
    plan_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    amount_before_vnd: Mapped[Decimal] = mapped_column(Numeric(18, 0))
    discount_vnd: Mapped[Decimal] = mapped_column(Numeric(18, 0))
    amount_after_vnd: Mapped[Decimal] = mapped_column(Numeric(18, 0))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_wallet_tx_idempotency"),
        Index(
            "ix_wallet_tx_user_created",
            "user_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"wtx_{secrets.token_urlsafe(16)}"
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(16), index=True)  # topup|debit|refund|adjust
    amount_vnd: Mapped[Decimal] = mapped_column(Numeric(18, 0))  # signed
    balance_after: Mapped[Decimal] = mapped_column(Numeric(18, 0))
    ref_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ref_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class CryptoNetwork(Base):
    __tablename__ = "crypto_networks"
    __table_args__ = (UniqueConstraint("key", name="uq_crypto_network_key"),)

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"cnet_{secrets.token_urlsafe(12)}"
    )
    key: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(128))
    chain_type: Mapped[str] = mapped_column(String(16), index=True)
    chain_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    native_symbol: Mapped[str | None] = mapped_column(String(16), nullable=True)
    min_confirmations: Mapped[int] = mapped_column(Integer, default=12)
    finality_blocks: Mapped[int] = mapped_column(Integer, default=64)
    scan_batch_size: Mapped[int] = mapped_column(Integer, default=1000)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class CryptoToken(Base):
    __tablename__ = "crypto_tokens"
    __table_args__ = (
        UniqueConstraint(
            "network_id",
            "symbol",
            "contract_address",
            name="uq_crypto_token_network_symbol_contract",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"ctok_{secrets.token_urlsafe(12)}"
    )
    network_id: Mapped[str] = mapped_column(ForeignKey("crypto_networks.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str] = mapped_column(String(128))
    contract_address: Mapped[str] = mapped_column(String(128), index=True)
    decimals: Mapped[int] = mapped_column(Integer, default=18)
    min_invoice_amount: Mapped[Decimal] = mapped_column(Numeric(36, 18), default=Decimal("1"))
    max_invoice_amount: Mapped[Decimal] = mapped_column(
        Numeric(36, 18), default=Decimal("100000")
    )
    dust_precision: Mapped[int] = mapped_column(Integer, default=6)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class CryptoRpcEndpoint(Base):
    __tablename__ = "crypto_rpc_endpoints"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"crpc_{secrets.token_urlsafe(12)}"
    )
    network_id: Mapped[str] = mapped_column(ForeignKey("crypto_networks.id"), index=True)
    url_enc: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(64))
    priority: Mapped[int] = mapped_column(Integer, default=100)
    rate_limit_per_sec: Mapped[int] = mapped_column(Integer, default=5)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    last_ok_at: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class CryptoWallet(Base):
    __tablename__ = "crypto_wallets"
    __table_args__ = (
        UniqueConstraint("network_id", "address", name="uq_crypto_wallet_network_address"),
    )

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"cwal_{secrets.token_urlsafe(12)}"
    )
    owner_type: Mapped[str] = mapped_column(String(16), default="system", index=True)
    owner_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    network_id: Mapped[str] = mapped_column(ForeignKey("crypto_networks.id"), index=True)
    address: Mapped[str] = mapped_column(String(128), index=True)
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    max_active_invoices: Mapped[int] = mapped_column(Integer, default=100)
    active_invoice_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class CryptoInvoice(Base):
    __tablename__ = "crypto_invoices"
    __table_args__ = (
        UniqueConstraint("merchant_id", "request_id", name="uq_crypto_invoice_merchant_request"),
        Index("ix_crypto_invoice_status_expires", "status", "expires_at"),
        Index(
            "ix_crypto_invoice_match",
            "network_id",
            "token_id",
            "address",
            "pay_amount",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"cinv_{secrets.token_urlsafe(16)}"
    )
    trans_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    request_id: Mapped[str] = mapped_column(String(128), index=True)
    merchant_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    network_id: Mapped[str] = mapped_column(ForeignKey("crypto_networks.id"), index=True)
    token_id: Mapped[str] = mapped_column(ForeignKey("crypto_tokens.id"), index=True)
    wallet_id: Mapped[str] = mapped_column(ForeignKey("crypto_wallets.id"), index=True)
    address: Mapped[str] = mapped_column(String(128), index=True)
    requested_amount: Mapped[Decimal] = mapped_column(Numeric(36, 18))
    pay_amount: Mapped[Decimal] = mapped_column(Numeric(36, 18))
    received_amount: Mapped[Decimal] = mapped_column(Numeric(36, 18), default=Decimal(0))
    currency_amount_vnd: Mapped[Decimal | None] = mapped_column(Numeric(18, 0), nullable=True)
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(36, 8), nullable=True)
    fx_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fx_locked_at: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(String(24), default="waiting", index=True)
    expires_at: Mapped[datetime] = mapped_column(index=True)
    paid_at: Mapped[datetime | None]
    canceled_at: Mapped[datetime | None]
    callback_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    success_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    from_address: Mapped[str | None] = mapped_column(String(128), nullable=True)
    transaction_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirmations: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class CryptoChainTransfer(Base):
    __tablename__ = "crypto_chain_transfers"
    __table_args__ = (
        UniqueConstraint("network_id", "tx_hash", "log_index", name="uq_crypto_transfer_log"),
    )

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"ctr_{secrets.token_urlsafe(16)}"
    )
    network_id: Mapped[str] = mapped_column(ForeignKey("crypto_networks.id"), index=True)
    token_id: Mapped[str] = mapped_column(ForeignKey("crypto_tokens.id"), index=True)
    tx_hash: Mapped[str] = mapped_column(String(128), index=True)
    log_index: Mapped[int] = mapped_column(Integer, default=0)
    from_address: Mapped[str] = mapped_column(String(128), index=True)
    to_address: Mapped[str] = mapped_column(String(128), index=True)
    amount_raw: Mapped[str] = mapped_column(String(96))
    amount_decimal: Mapped[Decimal] = mapped_column(Numeric(36, 18))
    block_number: Mapped[int] = mapped_column(Integer, index=True)
    block_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    block_time: Mapped[datetime | None]
    confirmations: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="seen", index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class CryptoInvoiceMatch(Base):
    __tablename__ = "crypto_invoice_matches"
    __table_args__ = (
        UniqueConstraint("invoice_id", "transfer_id", name="uq_crypto_invoice_transfer"),
    )

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"cim_{secrets.token_urlsafe(16)}"
    )
    invoice_id: Mapped[str] = mapped_column(ForeignKey("crypto_invoices.id"), index=True)
    transfer_id: Mapped[str] = mapped_column(ForeignKey("crypto_chain_transfers.id"), index=True)
    matched_amount: Mapped[Decimal] = mapped_column(Numeric(36, 18))
    match_type: Mapped[str] = mapped_column(String(24), default="exact")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class CryptoCallback(Base):
    __tablename__ = "crypto_callbacks"
    __table_args__ = (Index("ix_crypto_callbacks_state_next", "state", "next_retry_at"),)

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"ccb_{secrets.token_urlsafe(16)}"
    )
    invoice_id: Mapped[str] = mapped_column(ForeignKey("crypto_invoices.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=6)
    next_retry_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    last_status_code: Mapped[int | None]
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    sent_at: Mapped[datetime | None]


class CryptoWatcherCursor(Base):
    __tablename__ = "crypto_watcher_cursors"
    __table_args__ = (
        UniqueConstraint(
            "network_id", "token_id", "wallet_group_hash", name="uq_crypto_watcher_cursor"
        ),
    )

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"cwc_{secrets.token_urlsafe(12)}"
    )
    network_id: Mapped[str] = mapped_column(ForeignKey("crypto_networks.id"), index=True)
    token_id: Mapped[str] = mapped_column(ForeignKey("crypto_tokens.id"), index=True)
    wallet_group_hash: Mapped[str] = mapped_column(String(128), default="default")
    last_scanned_block: Mapped[int] = mapped_column(Integer, default=0)
    last_finalized_block: Mapped[int] = mapped_column(Integer, default=0)
    lock_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    locked_until: Mapped[datetime | None]
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"ntf_{secrets.token_urlsafe(16)}"
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    channel: Mapped[str] = mapped_column(String(16))  # in_app|email|telegram
    kind: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    read_at: Mapped[datetime | None]
    sent_at: Mapped[datetime | None]
    # Retry/DLQ fields. status='pending' (chờ gửi), 'sent' (đã set sent_at),
    # 'dead' (vượt max_attempts). next_run_at để dispatcher chỉ pick row due.
    status: Mapped[str] = mapped_column(
        String(16), default="pending", index=True
    )
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    next_run_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", "channel", name="uq_pref_user_kind_channel"),
    )

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"np_{secrets.token_urlsafe(12)}"
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    channel: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(default=True)
    muted_until: Mapped[datetime | None]
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class NotificationTemplate(Base):
    """Template tái sử dụng cho admin send single / broadcast.

    Field ``body_md`` nhận placeholder ``{{name}}``, ``{{email}}``, …
    được resolve khi gửi.
    """

    __tablename__ = "notification_templates"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"nt_{secrets.token_urlsafe(12)}"
    )
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    body_md: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class AppConfig(Base):
    """Cấu hình runtime, admin chỉnh từ UI mà không cần restart.

    `value_json` chứa toàn bộ payload (kể cả secret đã encrypt qua Fernet ở field
    `*_enc`). Helper `packages.config.runtime` sẽ encrypt/decrypt + cache.
    """

    __tablename__ = "app_configs"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ApiUsageDaily(Base):
    """Aggregate đếm request /v1/* theo ngày × user × api_key × endpoint_group.

    Middleware ``UsageMeteringMiddleware`` cộng dồn trong RAM rồi flush mỗi
    60s qua upsert (PostgreSQL ``ON CONFLICT``, SQLite ``ON CONFLICT``).
    Composite PK trùng natural key, đảm bảo idempotent flush.
    """

    __tablename__ = "api_usage_daily"
    __table_args__ = (
        Index("ix_api_usage_day_user", "day", "user_id"),
        Index("ix_api_usage_day_apikey", "day", "api_key_id"),
    )

    day: Mapped[_date_t] = mapped_column(Date, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    api_key_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    endpoint_group: Mapped[str] = mapped_column(String(32), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class IpBlocklist(Base):
    """Chặn IP/CIDR truy cập. Middleware kiểm trước RateLimit."""

    __tablename__ = "ip_blocklist"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"blk_{secrets.token_urlsafe(12)}"
    )
    cidr: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class UserNote(Base):
    """Admin ghi chú nội bộ về user."""

    __tablename__ = "user_notes"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"un_{secrets.token_urlsafe(12)}"
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    body: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class UserTag(Base):
    """Tag/segment cho user (vip, fraud_watch, ...)."""

    __tablename__ = "user_tags"
    __table_args__ = (
        UniqueConstraint("user_id", "tag", name="uq_user_tag"),
    )

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"ut_{secrets.token_urlsafe(12)}"
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    tag: Mapped[str] = mapped_column(String(64), index=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class DataExportRequest(Base):
    """User yêu cầu export data theo GDPR. Admin xử lý + sinh ZIP."""

    __tablename__ = "data_export_requests"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"dex_{secrets.token_urlsafe(12)}"
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(
        String(16), default="pending", index=True
    )  # pending | ready | failed | expired
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    completed_at: Mapped[datetime | None]
    expires_at: Mapped[datetime | None]


class LegalVersion(Base):
    """Version của Terms / Privacy Policy đang hiệu lực.

    Admin tạo version mới khi update; FE đọc version mới nhất theo `kind`.
    """

    __tablename__ = "legal_versions"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"lv_{secrets.token_urlsafe(12)}"
    )
    kind: Mapped[str] = mapped_column(String(16), index=True)  # terms | privacy
    version: Mapped[str] = mapped_column(String(32), index=True)
    content_md: Mapped[str] = mapped_column(Text)
    effective_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class TermsAcceptance(Base):
    """Log mỗi lần user accept Terms/Privacy với version cụ thể."""

    __tablename__ = "terms_acceptances"
    __table_args__ = (
        Index("ix_terms_acceptances_user_kind", "user_id", "kind"),
    )

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"tac_{secrets.token_urlsafe(12)}"
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # terms | privacy
    version: Mapped[str] = mapped_column(String(32))
    accepted_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)


class SecurityEvent(Base):
    """Log security event của user (login, password_change, 2fa_change,
    email_change, ip_change, api_key_rotate, …) cho FE Settings hiển thị."""

    __tablename__ = "security_events"
    __table_args__ = (
        Index("ix_security_events_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"sev_{secrets.token_urlsafe(12)}"
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class BillingProfile(Base):
    """Tax/billing profile của user (xuất hoá đơn doanh nghiệp)."""

    __tablename__ = "billing_profiles"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), primary_key=True
    )
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tax_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    billing_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class WithdrawalRequest(Base):
    """User yêu cầu rút tiền từ ví về bank account đã verify."""

    __tablename__ = "withdrawal_requests"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"wr_{secrets.token_urlsafe(12)}"
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    bank_account_id: Mapped[str] = mapped_column(
        ForeignKey("bank_accounts.id")
    )
    amount_vnd: Mapped[Decimal] = mapped_column(Numeric(18, 0))
    status: Mapped[str] = mapped_column(
        String(16), default="pending", index=True
    )  # pending | approved | rejected | paid | canceled
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    decided_at: Mapped[datetime | None]
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class SupportTicket(Base):
    """Ticket support đơn giản — user mở, admin reply qua message."""

    __tablename__ = "support_tickets"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"st_{secrets.token_urlsafe(12)}"
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    subject: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(16), default="open", index=True
    )  # open | replied | resolved | closed
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class TicketMessage(Base):
    __tablename__ = "ticket_messages"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"tm_{secrets.token_urlsafe(12)}"
    )
    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("support_tickets.id"), index=True
    )
    author_id: Mapped[str] = mapped_column(String(64))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


def _generate_order_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "DH" + "".join(secrets.choice(alphabet) for _ in range(6))
