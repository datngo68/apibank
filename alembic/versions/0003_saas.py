"""saas: users, billing, notifications + tenant columns on legacy tables

Revision ID: 0003_saas
Revises: 0002_poll_cursors
Create Date: 2026-05-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_saas"
down_revision: str | None = "0002_poll_cursors"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- users -----------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("role", sa.String(16), nullable=False, server_default="user"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("balance_vnd", sa.Numeric(18, 0), nullable=False, server_default="0"),
        sa.Column("locale", sa.String(8), nullable=False, server_default="vi"),
        sa.Column("telegram_chat_id", sa.String(64), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_role", "users", ["role"])
    op.create_index("ix_users_status", "users", ["status"])

    # ---- sessions --------------------------------------------------------
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_token_hash", "sessions", ["token_hash"], unique=True)
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])

    # ---- email tokens ----------------------------------------------------
    op.create_table(
        "email_tokens",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_email_tokens_user_id", "email_tokens", ["user_id"])
    op.create_index("ix_email_tokens_kind", "email_tokens", ["kind"])
    op.create_index("ix_email_tokens_token_hash", "email_tokens", ["token_hash"], unique=True)
    op.create_index("ix_email_tokens_expires_at", "email_tokens", ["expires_at"])

    # ---- two factors -----------------------------------------------------
    op.create_table(
        "two_factors",
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("secret_enc", sa.Text(), nullable=False),
        sa.Column("recovery_codes_enc", sa.JSON(), nullable=False),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # ---- oauth identities -----------------------------------------------
    op.create_table(
        "oauth_identities",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "subject", name="uq_oauth_provider_subject"),
    )
    op.create_index("ix_oauth_identities_user_id", "oauth_identities", ["user_id"])

    # ---- plans -----------------------------------------------------------
    op.create_table(
        "plans",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price_vnd", sa.Numeric(18, 0), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("daily_quota", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("monthly_quota", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("features_json", sa.JSON(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_plans_code", "plans", ["code"], unique=True)

    # ---- subscriptions ---------------------------------------------------
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("plan_id", sa.String(64), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])
    op.create_index("ix_subscriptions_plan_id", "subscriptions", ["plan_id"])
    op.create_index("ix_subscriptions_status", "subscriptions", ["status"])
    op.create_index("ix_subscriptions_expires_at", "subscriptions", ["expires_at"])

    # ---- invoices --------------------------------------------------------
    op.create_table(
        "invoices",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "subscription_id", sa.String(64), sa.ForeignKey("subscriptions.id"), nullable=True
        ),
        sa.Column("plan_code", sa.String(32), nullable=True),
        sa.Column("amount_vnd", sa.Numeric(18, 0), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="VND"),
        sa.Column("status", sa.String(16), nullable=False, server_default="paid"),
        sa.Column("wallet_tx_id", sa.String(64), nullable=True),
        sa.Column("pdf_path", sa.Text(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_invoices_user_id", "invoices", ["user_id"])
    op.create_index("ix_invoices_status", "invoices", ["status"])
    op.create_index("ix_invoices_issued_at", "invoices", ["issued_at"])

    # ---- wallet transactions --------------------------------------------
    op.create_table(
        "wallet_transactions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("amount_vnd", sa.Numeric(18, 0), nullable=False),
        sa.Column("balance_after", sa.Numeric(18, 0), nullable=False),
        sa.Column("ref_kind", sa.String(16), nullable=True),
        sa.Column("ref_id", sa.String(64), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_wallet_tx_idempotency"),
    )
    op.create_index("ix_wallet_transactions_user_id", "wallet_transactions", ["user_id"])
    op.create_index("ix_wallet_transactions_type", "wallet_transactions", ["type"])
    op.create_index(
        "ix_wallet_tx_user_created", "wallet_transactions", ["user_id", "created_at"]
    )

    # ---- notifications --------------------------------------------------
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_kind", "notifications", ["kind"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])

    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "kind", "channel", name="uq_pref_user_kind_channel"),
    )
    op.create_index("ix_notification_preferences_user_id", "notification_preferences", ["user_id"])

    # ---- mở rộng bảng cũ (nullable trước, backfill sau) ------------------
    with op.batch_alter_table("bank_accounts") as batch:
        batch.add_column(sa.Column("user_id", sa.String(64), nullable=True))
        batch.add_column(
            sa.Column("is_system_account", sa.Boolean(), nullable=False, server_default=sa.text("false"))
        )
        batch.add_column(
            sa.Column("polling_status", sa.String(16), nullable=False, server_default="idle")
        )
        batch.add_column(sa.Column("last_error", sa.Text(), nullable=True))
        batch.add_column(sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key(
            "fk_bank_accounts_user", "users", ["user_id"], ["id"]
        )
    op.create_index("ix_bank_accounts_user_id", "bank_accounts", ["user_id"])
    op.create_index("ix_bank_accounts_is_system_account", "bank_accounts", ["is_system_account"])

    with op.batch_alter_table("webhooks") as batch:
        batch.add_column(sa.Column("user_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("name", sa.String(255), nullable=True))
        batch.add_column(sa.Column("events_json", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key("fk_webhooks_user", "users", ["user_id"], ["id"])
    op.create_index("ix_webhooks_user_id", "webhooks", ["user_id"])

    with op.batch_alter_table("api_keys") as batch:
        batch.add_column(sa.Column("user_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("name", sa.String(255), nullable=True))
        batch.add_column(sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("last_used_ip", sa.String(64), nullable=True))
        batch.add_column(sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key("fk_api_keys_user", "users", ["user_id"], ["id"])
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_api_keys_user_id", table_name="api_keys")
    with op.batch_alter_table("api_keys") as batch:
        batch.drop_constraint("fk_api_keys_user", type_="foreignkey")
        batch.drop_column("expires_at")
        batch.drop_column("last_used_ip")
        batch.drop_column("last_used_at")
        batch.drop_column("name")
        batch.drop_column("user_id")

    op.drop_index("ix_webhooks_user_id", table_name="webhooks")
    with op.batch_alter_table("webhooks") as batch:
        batch.drop_constraint("fk_webhooks_user", type_="foreignkey")
        batch.drop_column("last_delivery_at")
        batch.drop_column("events_json")
        batch.drop_column("name")
        batch.drop_column("user_id")

    op.drop_index("ix_bank_accounts_is_system_account", table_name="bank_accounts")
    op.drop_index("ix_bank_accounts_user_id", table_name="bank_accounts")
    with op.batch_alter_table("bank_accounts") as batch:
        batch.drop_constraint("fk_bank_accounts_user", type_="foreignkey")
        batch.drop_column("verified_at")
        batch.drop_column("last_error")
        batch.drop_column("polling_status")
        batch.drop_column("is_system_account")
        batch.drop_column("user_id")

    op.drop_index("ix_notification_preferences_user_id", table_name="notification_preferences")
    op.drop_table("notification_preferences")
    op.drop_index("ix_notifications_created_at", table_name="notifications")
    op.drop_index("ix_notifications_kind", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_wallet_tx_user_created", table_name="wallet_transactions")
    op.drop_index("ix_wallet_transactions_type", table_name="wallet_transactions")
    op.drop_index("ix_wallet_transactions_user_id", table_name="wallet_transactions")
    op.drop_table("wallet_transactions")
    op.drop_index("ix_invoices_issued_at", table_name="invoices")
    op.drop_index("ix_invoices_status", table_name="invoices")
    op.drop_index("ix_invoices_user_id", table_name="invoices")
    op.drop_table("invoices")
    op.drop_index("ix_subscriptions_expires_at", table_name="subscriptions")
    op.drop_index("ix_subscriptions_status", table_name="subscriptions")
    op.drop_index("ix_subscriptions_plan_id", table_name="subscriptions")
    op.drop_index("ix_subscriptions_user_id", table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_index("ix_plans_code", table_name="plans")
    op.drop_table("plans")
    op.drop_index("ix_oauth_identities_user_id", table_name="oauth_identities")
    op.drop_table("oauth_identities")
    op.drop_table("two_factors")
    op.drop_index("ix_email_tokens_expires_at", table_name="email_tokens")
    op.drop_index("ix_email_tokens_token_hash", table_name="email_tokens")
    op.drop_index("ix_email_tokens_kind", table_name="email_tokens")
    op.drop_index("ix_email_tokens_user_id", table_name="email_tokens")
    op.drop_table("email_tokens")
    op.drop_index("ix_sessions_expires_at", table_name="sessions")
    op.drop_index("ix_sessions_token_hash", table_name="sessions")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("ix_users_status", table_name="users")
    op.drop_index("ix_users_role", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
