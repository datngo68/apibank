"""api_usage_daily: aggregate request counts per day/user/api_key/endpoint

Revision ID: 0008_api_usage_daily
Revises: 0007_coupons
Create Date: 2026-05-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_api_usage_daily"
down_revision: str | None = "0007_coupons"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_usage_daily",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("api_key_id", sa.String(64), nullable=False),
        sa.Column("endpoint_group", sa.String(32), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "day", "user_id", "api_key_id", "endpoint_group",
            name="pk_api_usage_daily",
        ),
    )
    op.create_index(
        "ix_api_usage_day_user", "api_usage_daily", ["day", "user_id"]
    )
    op.create_index(
        "ix_api_usage_day_apikey", "api_usage_daily", ["day", "api_key_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_api_usage_day_apikey", table_name="api_usage_daily")
    op.drop_index("ix_api_usage_day_user", table_name="api_usage_daily")
    op.drop_table("api_usage_daily")
