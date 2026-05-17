"""2fa replay guard + lockout exponential

Revision ID: 0005_2fa_replay_guard
Revises: 0004_app_configs
Create Date: 2026-05-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_2fa_replay_guard"
down_revision: str | None = "0004_app_configs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("two_factors") as batch:
        batch.add_column(sa.Column("last_totp_code", sa.String(8), nullable=True))
        batch.add_column(sa.Column("last_totp_used_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("two_factors") as batch:
        batch.drop_column("last_totp_used_at")
        batch.drop_column("last_totp_code")
