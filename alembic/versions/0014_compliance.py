"""compliance: data_export_requests + legal_versions + terms_acceptances

Revision ID: 0014_compliance
Revises: 0013_plan_archive
Create Date: 2026-05-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014_compliance"
down_revision: str | None = "0013_plan_archive"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "data_export_requests",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "requested_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_data_export_user", "data_export_requests", ["user_id"]
    )
    op.create_index(
        "ix_data_export_status", "data_export_requests", ["status"]
    )

    op.create_table(
        "legal_versions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column(
            "effective_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("created_by", sa.String(64), nullable=True),
    )
    op.create_index("ix_legal_versions_kind", "legal_versions", ["kind"])
    op.create_index(
        "ix_legal_versions_version", "legal_versions", ["version"]
    )

    op.create_table(
        "terms_acceptances",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column(
            "accepted_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("ip", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_terms_acceptances_user", "terms_acceptances", ["user_id"]
    )
    op.create_index(
        "ix_terms_acceptances_user_kind",
        "terms_acceptances",
        ["user_id", "kind"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_terms_acceptances_user_kind", table_name="terms_acceptances"
    )
    op.drop_index(
        "ix_terms_acceptances_user", table_name="terms_acceptances"
    )
    op.drop_table("terms_acceptances")
    op.drop_index("ix_legal_versions_version", table_name="legal_versions")
    op.drop_index("ix_legal_versions_kind", table_name="legal_versions")
    op.drop_table("legal_versions")
    op.drop_index("ix_data_export_status", table_name="data_export_requests")
    op.drop_index("ix_data_export_user", table_name="data_export_requests")
    op.drop_table("data_export_requests")
