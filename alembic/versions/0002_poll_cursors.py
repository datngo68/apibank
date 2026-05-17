"""poll cursors

Revision ID: 0002_poll_cursors
Revises: 0001_initial
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_poll_cursors"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "poll_cursors",
        sa.Column(
            "bank_account_id",
            sa.String(64),
            sa.ForeignKey("bank_accounts.id"),
            primary_key=True,
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_ref_no", sa.String(128), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("poll_cursors")
