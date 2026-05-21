"""notification_templates + notification_preferences.muted_until

Revision ID: 0015_notif_templates
Revises: 0014_compliance
Create Date: 2026-05-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015_notif_templates"
down_revision: str | None = "0014_compliance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_templates",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("code", name="uq_notification_templates_code"),
    )
    op.create_index(
        "ix_notification_templates_code", "notification_templates", ["code"]
    )

    with op.batch_alter_table("notification_preferences") as batch:
        batch.add_column(
            sa.Column("muted_until", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("notification_preferences") as batch:
        batch.drop_column("muted_until")
    op.drop_index(
        "ix_notification_templates_code", table_name="notification_templates"
    )
    op.drop_table("notification_templates")
