"""phase 4 user-facing tables

- security_events
- billing_profiles
- withdrawal_requests
- support_tickets + ticket_messages
- bank_accounts.is_primary
- api_keys.ip_allowlist_json + mode
- users.billing_email
- webhooks.test_mode

Revision ID: 0016_phase4
Revises: 0015_notif_templates
Create Date: 2026-05-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016_phase4"
down_revision: str | None = "0015_notif_templates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # security_events
    op.create_table(
        "security_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_security_events_user", "security_events", ["user_id"])
    op.create_index(
        "ix_security_events_kind", "security_events", ["kind"]
    )
    op.create_index(
        "ix_security_events_created", "security_events", ["created_at"]
    )
    op.create_index(
        "ix_security_events_user_created",
        "security_events",
        ["user_id", "created_at"],
    )

    # billing_profiles
    op.create_table(
        "billing_profiles",
        sa.Column(
            "user_id",
            sa.String(64),
            sa.ForeignKey("users.id"),
            primary_key=True,
        ),
        sa.Column("company_name", sa.String(255), nullable=True),
        sa.Column("tax_code", sa.String(32), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("billing_email", sa.String(255), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # withdrawal_requests
    op.create_table(
        "withdrawal_requests",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "bank_account_id",
            sa.String(64),
            sa.ForeignKey("bank_accounts.id"),
            nullable=False,
        ),
        sa.Column("amount_vnd", sa.Numeric(18, 0), nullable=False),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default="pending"
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_withdrawal_requests_user", "withdrawal_requests", ["user_id"]
    )
    op.create_index(
        "ix_withdrawal_requests_status", "withdrawal_requests", ["status"]
    )
    op.create_index(
        "ix_withdrawal_requests_requested",
        "withdrawal_requests",
        ["requested_at"],
    )

    # support_tickets + ticket_messages
    op.create_table(
        "support_tickets",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default="open"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_support_tickets_user", "support_tickets", ["user_id"])
    op.create_index(
        "ix_support_tickets_status", "support_tickets", ["status"]
    )
    op.create_index(
        "ix_support_tickets_created", "support_tickets", ["created_at"]
    )

    op.create_table(
        "ticket_messages",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "ticket_id",
            sa.String(64),
            sa.ForeignKey("support_tickets.id"),
            nullable=False,
        ),
        sa.Column("author_id", sa.String(64), nullable=False),
        sa.Column(
            "is_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_ticket_messages_ticket", "ticket_messages", ["ticket_id"]
    )
    op.create_index(
        "ix_ticket_messages_created", "ticket_messages", ["created_at"]
    )

    # bank_accounts.is_primary
    with op.batch_alter_table("bank_accounts") as batch:
        batch.add_column(
            sa.Column(
                "is_primary",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )

    # api_keys.ip_allowlist_json + mode
    with op.batch_alter_table("api_keys") as batch:
        batch.add_column(
            sa.Column(
                "ip_allowlist_json",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            )
        )
        batch.add_column(
            sa.Column(
                "mode", sa.String(8), nullable=False, server_default="live"
            )
        )

    # users.billing_email
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("billing_email", sa.String(255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("billing_email")
    with op.batch_alter_table("api_keys") as batch:
        batch.drop_column("mode")
        batch.drop_column("ip_allowlist_json")
    with op.batch_alter_table("bank_accounts") as batch:
        batch.drop_column("is_primary")

    op.drop_index("ix_ticket_messages_created", table_name="ticket_messages")
    op.drop_index("ix_ticket_messages_ticket", table_name="ticket_messages")
    op.drop_table("ticket_messages")
    op.drop_index("ix_support_tickets_created", table_name="support_tickets")
    op.drop_index("ix_support_tickets_status", table_name="support_tickets")
    op.drop_index("ix_support_tickets_user", table_name="support_tickets")
    op.drop_table("support_tickets")

    op.drop_index(
        "ix_withdrawal_requests_requested", table_name="withdrawal_requests"
    )
    op.drop_index(
        "ix_withdrawal_requests_status", table_name="withdrawal_requests"
    )
    op.drop_index(
        "ix_withdrawal_requests_user", table_name="withdrawal_requests"
    )
    op.drop_table("withdrawal_requests")

    op.drop_table("billing_profiles")

    op.drop_index(
        "ix_security_events_user_created", table_name="security_events"
    )
    op.drop_index("ix_security_events_created", table_name="security_events")
    op.drop_index("ix_security_events_kind", table_name="security_events")
    op.drop_index("ix_security_events_user", table_name="security_events")
    op.drop_table("security_events")
