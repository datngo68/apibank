from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
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
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    balance_vnd: Mapped[Decimal] = mapped_column(Numeric(18, 0), default=Decimal(0))
    locale: Mapped[str] = mapped_column(String(8), default="vi")
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
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


def _generate_order_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "DH" + "".join(secrets.choice(alphabet) for _ in range(6))
