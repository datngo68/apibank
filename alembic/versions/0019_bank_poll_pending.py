"""add pending-order bank polling policy

Revision ID: 0019_bank_poll_pending
Revises: 0018_bank_session
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019_bank_poll_pending"
down_revision: str | None = "0018_bank_session"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "bank_accounts",
        sa.Column(
            "poll_only_when_pending",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.execute(
        sa.text(
            "UPDATE bank_accounts "
            "SET poll_only_when_pending = true "
            "WHERE bank_code = 'MB'"
        )
    )


def downgrade() -> None:
    op.drop_column("bank_accounts", "poll_only_when_pending")
