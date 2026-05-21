"""ip_blocklist + notifications retention indices

Revision ID: 0010_ip_blocklist
Revises: 0009_notification_dlq
Create Date: 2026-05-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010_ip_blocklist"
down_revision: str | None = "0009_notification_dlq"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ip_blocklist",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("cidr", sa.String(64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("cidr", name="uq_ip_blocklist_cidr"),
    )
    op.create_index("ix_ip_blocklist_cidr", "ip_blocklist", ["cidr"])


def downgrade() -> None:
    op.drop_index("ix_ip_blocklist_cidr", table_name="ip_blocklist")
    op.drop_table("ip_blocklist")
