"""plans: add archived_at + experiment_key

Revision ID: 0013_plan_archive
Revises: 0012_admin_role_extra
Create Date: 2026-05-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_plan_archive"
down_revision: str | None = "0012_admin_role_extra"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("plans") as batch:
        batch.add_column(
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(sa.Column("experiment_key", sa.String(64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("plans") as batch:
        batch.drop_column("experiment_key")
        batch.drop_column("archived_at")
