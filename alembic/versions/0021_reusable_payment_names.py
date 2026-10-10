"""Separate public identity from temporally reserved payment content."""

import sqlalchemy as sa

from alembic import op

revision = "0021_reusable_payment_names"
down_revision = "0020_order_payment_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("timestamp_reliable", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("orders", sa.Column("transfer_content", sa.String(96), nullable=True))
    op.create_index("ix_orders_transfer_content", "orders", ["transfer_content"])
    op.create_table(
        "payment_name_reservations",
        sa.Column("bank_account_id", sa.String(64), primary_key=True),
        sa.Column("content", sa.String(96), primary_key=True),
        sa.Column("reserved_until", sa.DateTime(timezone=True), nullable=False),
    )
    # No historical cancellation timestamp exists: expiry is the conservative fallback.
    op.execute(
        sa.text("""
        INSERT INTO payment_name_reservations (bank_account_id, content, reserved_until)
        SELECT bank_account_id, code,
               MAX(CASE WHEN status = 'paid' AND paid_at IS NOT NULL
                        THEN paid_at ELSE expired_at END) + INTERVAL '7 days'
        FROM orders
        WHERE code LIKE '% chuyen tien'
        GROUP BY bank_account_id, code
    """)
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM orders WHERE transfer_content IS NOT NULL")
    ):
        raise RuntimeError("Cannot downgrade after reusable payment orders exist")
    op.drop_column("transactions", "timestamp_reliable")
    op.drop_table("payment_name_reservations")
    op.drop_index("ix_orders_transfer_content", table_name="orders")
    op.drop_column("orders", "transfer_content")
