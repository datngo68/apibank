"""add app_configs

Revision ID: 0004_app_configs
Revises: 0003_saas
Create Date: 2026-05-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_app_configs"
down_revision: str | None = "0003_saas"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_configs",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("app_configs")
