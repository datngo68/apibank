"""notifications: add retry/DLQ fields (attempt, status, next_run_at, last_error)

Revision ID: 0009_notification_dlq
Revises: 0008_api_usage_daily
Create Date: 2026-05-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_notification_dlq"
down_revision: str | None = "0008_api_usage_daily"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("notifications") as batch:
        batch.add_column(
            sa.Column(
                "status", sa.String(16), nullable=False, server_default="pending"
            )
        )
        batch.add_column(
            sa.Column("attempt", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column(
                "max_attempts", sa.Integer(), nullable=False, server_default="5"
            )
        )
        batch.add_column(
            sa.Column(
                "next_run_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
        )
        batch.add_column(sa.Column("last_error", sa.Text(), nullable=True))
    op.create_index(
        "ix_notifications_status", "notifications", ["status"]
    )
    op.create_index(
        "ix_notifications_next_run", "notifications", ["next_run_at"]
    )

    # Backfill: rows đã có sent_at → status='sent'.
    op.execute(
        "UPDATE notifications SET status='sent' WHERE sent_at IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_next_run", table_name="notifications")
    op.drop_index("ix_notifications_status", table_name="notifications")
    with op.batch_alter_table("notifications") as batch:
        batch.drop_column("last_error")
        batch.drop_column("next_run_at")
        batch.drop_column("max_attempts")
        batch.drop_column("attempt")
        batch.drop_column("status")
