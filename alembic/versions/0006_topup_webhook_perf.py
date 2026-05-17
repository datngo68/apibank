"""topup webhook performance optimizations

- webhook_attempts: thêm cột claimed_at + composite index (status, next_run_at)
- orders: thêm cột user_id để denormalize topup owner

Revision ID: 0006_topup_webhook_perf
Revises: 0005_2fa_replay_guard
Create Date: 2026-05-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_topup_webhook_perf"
down_revision: str | None = "0005_2fa_replay_guard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("webhook_attempts") as batch:
        batch.add_column(
            sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.create_index(
            "ix_webhook_attempts_status_next",
            ["status", "next_run_at"],
        )

    with op.batch_alter_table("orders") as batch:
        batch.add_column(sa.Column("user_id", sa.String(64), nullable=True))
        batch.create_index("ix_orders_user_id", ["user_id"])

    # Backfill: tách topup orders (có metadata.user_id) → cập nhật cột user_id
    # để dashboard query nhanh ngay sau migration. Chạy raw SQL vì JSON path
    # khác giữa Postgres và SQLite — dùng giá trị rỗng-an-toàn cho cả 2.
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        # `?` chỉ áp dụng cho jsonb, không phải json. Cast trước khi check.
        # Cũng tránh metadata_json IS NULL bằng coalesce.
        bind.execute(
            sa.text(
                """
                UPDATE orders
                SET user_id = metadata_json->>'user_id'
                WHERE COALESCE(metadata_json::jsonb ? 'user_id', false)
                """
            )
        )
    elif dialect == "sqlite":
        # SQLite JSON1 extension: json_extract(metadata_json, '$.user_id')
        bind.execute(
            sa.text(
                """
                UPDATE orders
                SET user_id = json_extract(metadata_json, '$.user_id')
                WHERE json_extract(metadata_json, '$.user_id') IS NOT NULL
                """
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("orders") as batch:
        batch.drop_index("ix_orders_user_id")
        batch.drop_column("user_id")

    with op.batch_alter_table("webhook_attempts") as batch:
        batch.drop_index("ix_webhook_attempts_status_next")
        batch.drop_column("claimed_at")
