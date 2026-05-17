"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bank_accounts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("bank_code", sa.String(16), nullable=False),
        sa.Column("account_no", sa.String(64), nullable=False),
        sa.Column("account_holder", sa.String(255), nullable=False),
        sa.Column("credentials_enc", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_poll_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("polling_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_bank_accounts_bank_code", "bank_accounts", ["bank_code"])
    op.create_index("ix_bank_accounts_account_no", "bank_accounts", ["account_no"])
    op.create_index("ix_bank_accounts_status", "bank_accounts", ["status"])

    op.create_table(
        "orders",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("code", sa.String(16), nullable=False, unique=True),
        sa.Column("amount_vnd", sa.Numeric(18, 0), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "bank_account_id", sa.String(64), sa.ForeignKey("bank_accounts.id"), nullable=False
        ),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_tx_id", sa.String(64), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("customer_ref", sa.String(255), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_index("ix_orders_expired_at", "orders", ["expired_at"])
    op.create_index("ix_orders_bank_account_id", "orders", ["bank_account_id"])
    op.create_index("ix_orders_code", "orders", ["code"])

    op.create_table(
        "transactions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "bank_account_id", sa.String(64), sa.ForeignKey("bank_accounts.id"), nullable=False
        ),
        sa.Column("bank_ref_no", sa.String(128), nullable=False),
        sa.Column("amount_vnd", sa.Numeric(18, 0), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_json", sa.JSON(), nullable=False),
        sa.Column("matched_order_id", sa.String(64), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("bank_account_id", "bank_ref_no", name="uq_transaction_bank_ref"),
    )
    # orders.paid_tx_id là tham chiếu mềm; bỏ FK constraint để tương thích SQLite
    # (vẫn được định nghĩa ở ORM models để navigate relationship).
    op.create_index("ix_transactions_bank_account_id", "transactions", ["bank_account_id"])
    op.create_index("ix_transactions_bank_ref_no", "transactions", ["bank_ref_no"])
    op.create_index("ix_transactions_posted_at", "transactions", ["posted_at"])
    op.create_index("ix_transactions_state", "transactions", ["state"])

    op.create_table(
        "webhooks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("secret_enc", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("headers_json", sa.JSON(), nullable=False),
        sa.Column("ip_allowlist", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_webhooks_owner_id", "webhooks", ["owner_id"])

    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("key_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_api_keys_owner_id", "api_keys", ["owner_id"])

    op.create_table(
        "webhook_attempts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("webhook_id", sa.String(64), sa.ForeignKey("webhooks.id"), nullable=False),
        sa.Column("order_id", sa.String(64), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column(
            "transaction_id", sa.String(64), sa.ForeignKey("transactions.id"), nullable=False
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("signature", sa.Text(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_webhook_attempts_status", "webhook_attempts", ["status"])
    op.create_index("ix_webhook_attempts_next_run_at", "webhook_attempts", ["next_run_at"])

    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("api_key_id", sa.String(64), sa.ForeignKey("api_keys.id"), nullable=False),
        sa.Column("request_hash", sa.String(128), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("api_key_id", "key", name="uq_idempotency_api_key"),
    )
    op.create_index("ix_idempotency_keys_api_key_id", "idempotency_keys", ["api_key_id"])
    op.create_index("ix_idempotency_keys_expires_at", "idempotency_keys", ["expires_at"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("action", sa.String(255), nullable=False),
        sa.Column("target_type", sa.String(255), nullable=False),
        sa.Column("target_id", sa.String(255), nullable=False),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("before_json", sa.JSON(), nullable=True),
        sa.Column("after_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_target_id", "audit_logs", ["target_id"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("idempotency_keys")
    op.drop_table("webhook_attempts")
    op.drop_table("api_keys")
    op.drop_table("webhooks")
    op.drop_table("transactions")
    op.drop_table("orders")
    op.drop_table("bank_accounts")
