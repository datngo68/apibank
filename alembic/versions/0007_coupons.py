"""coupons: discount codes for subscription purchase

- New tables: coupons, coupon_redemptions
- Invoices: thêm coupon_code, discount_vnd, original_amount_vnd

Revision ID: 0007_coupons
Revises: 0006_topup_webhook_perf
Create Date: 2026-05-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_coupons"
down_revision: str | None = "0006_topup_webhook_perf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- coupons ---------------------------------------------------------
    op.create_table(
        "coupons",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("discount_type", sa.String(16), nullable=False),
        sa.Column("percent_off", sa.Integer(), nullable=True),
        sa.Column("amount_off_vnd", sa.Numeric(18, 0), nullable=True),
        sa.Column("max_discount_vnd", sa.Numeric(18, 0), nullable=True),
        sa.Column("min_amount_vnd", sa.Numeric(18, 0), nullable=True),
        sa.Column("max_redemptions", sa.Integer(), nullable=True),
        sa.Column("max_per_user", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("redeemed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("plan_codes_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("code", name="uq_coupons_code"),
    )
    op.create_index("ix_coupons_code", "coupons", ["code"])
    op.create_index("ix_coupons_active", "coupons", ["active"])
    op.create_index("ix_coupons_valid_until", "coupons", ["valid_until"])

    # ---- coupon_redemptions ---------------------------------------------
    op.create_table(
        "coupon_redemptions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "coupon_id", sa.String(64), sa.ForeignKey("coupons.id"), nullable=False
        ),
        sa.Column("coupon_code", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "invoice_id", sa.String(64), sa.ForeignKey("invoices.id"), nullable=True
        ),
        sa.Column(
            "subscription_id",
            sa.String(64),
            sa.ForeignKey("subscriptions.id"),
            nullable=True,
        ),
        sa.Column("plan_code", sa.String(32), nullable=True),
        sa.Column("amount_before_vnd", sa.Numeric(18, 0), nullable=False),
        sa.Column("discount_vnd", sa.Numeric(18, 0), nullable=False),
        sa.Column("amount_after_vnd", sa.Numeric(18, 0), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_coupon_redemptions_coupon_id", "coupon_redemptions", ["coupon_id"]
    )
    op.create_index(
        "ix_coupon_redemptions_coupon_code", "coupon_redemptions", ["coupon_code"]
    )
    op.create_index("ix_coupon_redemptions_user_id", "coupon_redemptions", ["user_id"])
    op.create_index(
        "ix_coupon_redemptions_created_at", "coupon_redemptions", ["created_at"]
    )
    op.create_index(
        "ix_coupon_redemptions_coupon_user",
        "coupon_redemptions",
        ["coupon_id", "user_id"],
    )

    # ---- invoices: thêm cột tracking discount ---------------------------
    with op.batch_alter_table("invoices") as batch:
        batch.add_column(sa.Column("coupon_code", sa.String(64), nullable=True))
        batch.add_column(
            sa.Column(
                "discount_vnd",
                sa.Numeric(18, 0),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(
            sa.Column("original_amount_vnd", sa.Numeric(18, 0), nullable=True)
        )
    op.create_index("ix_invoices_coupon_code", "invoices", ["coupon_code"])


def downgrade() -> None:
    op.drop_index("ix_invoices_coupon_code", table_name="invoices")
    with op.batch_alter_table("invoices") as batch:
        batch.drop_column("original_amount_vnd")
        batch.drop_column("discount_vnd")
        batch.drop_column("coupon_code")

    op.drop_index("ix_coupon_redemptions_coupon_user", table_name="coupon_redemptions")
    op.drop_index("ix_coupon_redemptions_created_at", table_name="coupon_redemptions")
    op.drop_index("ix_coupon_redemptions_user_id", table_name="coupon_redemptions")
    op.drop_index("ix_coupon_redemptions_coupon_code", table_name="coupon_redemptions")
    op.drop_index("ix_coupon_redemptions_coupon_id", table_name="coupon_redemptions")
    op.drop_table("coupon_redemptions")

    op.drop_index("ix_coupons_valid_until", table_name="coupons")
    op.drop_index("ix_coupons_active", table_name="coupons")
    op.drop_index("ix_coupons_code", table_name="coupons")
    op.drop_table("coupons")
