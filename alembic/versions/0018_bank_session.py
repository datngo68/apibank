"""persist encrypted bank sessions

Revision ID: 0018_bank_session
Revises: 0017_crypto_gateway
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018_bank_session"
down_revision: str | None = "0017_crypto_gateway"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("bank_accounts", sa.Column("session_enc", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("bank_accounts", "session_enc")
