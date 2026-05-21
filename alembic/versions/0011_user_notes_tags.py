"""user_notes + user_tags tables

Revision ID: 0011_user_notes_tags
Revises: 0010_ip_blocklist
Create Date: 2026-05-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011_user_notes_tags"
down_revision: str | None = "0010_ip_blocklist"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_notes",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_user_notes_user", "user_notes", ["user_id"])
    op.create_index("ix_user_notes_created", "user_notes", ["created_at"])

    op.create_table(
        "user_tags",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("tag", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "tag", name="uq_user_tag"),
    )
    op.create_index("ix_user_tags_user", "user_tags", ["user_id"])
    op.create_index("ix_user_tags_tag", "user_tags", ["tag"])


def downgrade() -> None:
    op.drop_index("ix_user_tags_tag", table_name="user_tags")
    op.drop_index("ix_user_tags_user", table_name="user_tags")
    op.drop_table("user_tags")
    op.drop_index("ix_user_notes_created", table_name="user_notes")
    op.drop_index("ix_user_notes_user", table_name="user_notes")
    op.drop_table("user_notes")
