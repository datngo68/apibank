"""Expand payment codes for Vietnamese full names; keep the unique index."""

import sqlalchemy as sa

from alembic import op

revision = "0020_order_payment_names"
down_revision = "0019_bank_poll_pending"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("orders") as batch:
        batch.alter_column("code", existing_type=sa.String(16), type_=sa.String(96))


def downgrade() -> None:
    # Refuse truncation: existing names cannot fit in the old schema.
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT count(*) FROM orders WHERE length(code) > 16")):
        raise RuntimeError("Cannot downgrade while full-name payment codes exist")
    with op.batch_alter_table("orders") as batch:
        batch.alter_column("code", existing_type=sa.String(96), type_=sa.String(16))
