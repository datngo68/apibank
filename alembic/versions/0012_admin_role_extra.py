"""users: add admin_role_extra column for multi-admin role matrix

Revision ID: 0012_admin_role_extra
Revises: 0011_user_notes_tags
Create Date: 2026-05-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012_admin_role_extra"
down_revision: str | None = "0011_user_notes_tags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("admin_role_extra", sa.String(16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("admin_role_extra")
