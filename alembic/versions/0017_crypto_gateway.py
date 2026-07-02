"""crypto gateway tables

Revision ID: 0017_crypto_gateway
Revises: 0016_phase4
Create Date: 2026-07-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_crypto_gateway"
down_revision: str | None = "0016_phase4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "crypto_networks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("key", sa.String(32), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("chain_type", sa.String(16), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=True),
        sa.Column("native_symbol", sa.String(16), nullable=True),
        sa.Column("min_confirmations", sa.Integer(), nullable=False, server_default="12"),
        sa.Column("finality_blocks", sa.Integer(), nullable=False, server_default="64"),
        sa.Column("scan_batch_size", sa.Integer(), nullable=False, server_default="1000"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("key", name="uq_crypto_network_key"),
    )
    op.create_index("ix_crypto_networks_key", "crypto_networks", ["key"])
    op.create_index("ix_crypto_networks_chain_type", "crypto_networks", ["chain_type"])
    op.create_index("ix_crypto_networks_status", "crypto_networks", ["status"])

    op.create_table(
        "crypto_tokens",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("network_id", sa.String(64), sa.ForeignKey("crypto_networks.id"), nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("contract_address", sa.String(128), nullable=False),
        sa.Column("decimals", sa.Integer(), nullable=False, server_default="18"),
        sa.Column("min_invoice_amount", sa.Numeric(36, 18), nullable=False),
        sa.Column("max_invoice_amount", sa.Numeric(36, 18), nullable=False),
        sa.Column("dust_precision", sa.Integer(), nullable=False, server_default="6"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "network_id", "symbol", "contract_address", name="uq_crypto_token_network_symbol_contract"
        ),
    )
    op.create_index("ix_crypto_tokens_network_id", "crypto_tokens", ["network_id"])
    op.create_index("ix_crypto_tokens_symbol", "crypto_tokens", ["symbol"])
    op.create_index("ix_crypto_tokens_contract_address", "crypto_tokens", ["contract_address"])
    op.create_index("ix_crypto_tokens_status", "crypto_tokens", ["status"])

    op.create_table(
        "crypto_rpc_endpoints",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("network_id", sa.String(64), sa.ForeignKey("crypto_networks.id"), nullable=False),
        sa.Column("url_enc", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("rate_limit_per_sec", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("last_ok_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_crypto_rpc_endpoints_network_id", "crypto_rpc_endpoints", ["network_id"])
    op.create_index("ix_crypto_rpc_endpoints_status", "crypto_rpc_endpoints", ["status"])

    op.create_table(
        "crypto_wallets",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_type", sa.String(16), nullable=False, server_default="system"),
        sa.Column("owner_id", sa.String(64), nullable=True),
        sa.Column("network_id", sa.String(64), sa.ForeignKey("crypto_networks.id"), nullable=False),
        sa.Column("address", sa.String(128), nullable=False),
        sa.Column("label", sa.String(128), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("max_active_invoices", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("active_invoice_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("network_id", "address", name="uq_crypto_wallet_network_address"),
    )
    op.create_index("ix_crypto_wallets_owner_type", "crypto_wallets", ["owner_type"])
    op.create_index("ix_crypto_wallets_owner_id", "crypto_wallets", ["owner_id"])
    op.create_index("ix_crypto_wallets_network_id", "crypto_wallets", ["network_id"])
    op.create_index("ix_crypto_wallets_address", "crypto_wallets", ["address"])
    op.create_index("ix_crypto_wallets_status", "crypto_wallets", ["status"])

    op.create_table(
        "crypto_invoices",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("trans_id", sa.String(32), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("merchant_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("network_id", sa.String(64), sa.ForeignKey("crypto_networks.id"), nullable=False),
        sa.Column("token_id", sa.String(64), sa.ForeignKey("crypto_tokens.id"), nullable=False),
        sa.Column("wallet_id", sa.String(64), sa.ForeignKey("crypto_wallets.id"), nullable=False),
        sa.Column("address", sa.String(128), nullable=False),
        sa.Column("requested_amount", sa.Numeric(36, 18), nullable=False),
        sa.Column("pay_amount", sa.Numeric(36, 18), nullable=False),
        sa.Column("received_amount", sa.Numeric(36, 18), nullable=False, server_default="0"),
        sa.Column("currency_amount_vnd", sa.Numeric(18, 0), nullable=True),
        sa.Column("fx_rate", sa.Numeric(36, 8), nullable=True),
        sa.Column("fx_source", sa.String(64), nullable=True),
        sa.Column("fx_locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="waiting"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("callback_url", sa.Text(), nullable=True),
        sa.Column("success_url", sa.Text(), nullable=True),
        sa.Column("cancel_url", sa.Text(), nullable=True),
        sa.Column("webhook_secret_enc", sa.Text(), nullable=True),
        sa.Column("from_address", sa.String(128), nullable=True),
        sa.Column("transaction_id", sa.String(128), nullable=True),
        sa.Column("confirmations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("merchant_id", "request_id", name="uq_crypto_invoice_merchant_request"),
        sa.UniqueConstraint("trans_id", name="uq_crypto_invoices_trans_id"),
    )
    op.create_index("ix_crypto_invoices_trans_id", "crypto_invoices", ["trans_id"])
    op.create_index("ix_crypto_invoices_request_id", "crypto_invoices", ["request_id"])
    op.create_index("ix_crypto_invoices_merchant_id", "crypto_invoices", ["merchant_id"])
    op.create_index("ix_crypto_invoices_user_id", "crypto_invoices", ["user_id"])
    op.create_index("ix_crypto_invoices_network_id", "crypto_invoices", ["network_id"])
    op.create_index("ix_crypto_invoices_token_id", "crypto_invoices", ["token_id"])
    op.create_index("ix_crypto_invoices_wallet_id", "crypto_invoices", ["wallet_id"])
    op.create_index("ix_crypto_invoices_address", "crypto_invoices", ["address"])
    op.create_index("ix_crypto_invoices_status", "crypto_invoices", ["status"])
    op.create_index("ix_crypto_invoices_expires_at", "crypto_invoices", ["expires_at"])
    op.create_index("ix_crypto_invoice_status_expires", "crypto_invoices", ["status", "expires_at"])
    op.create_index(
        "ix_crypto_invoice_match", "crypto_invoices", ["network_id", "token_id", "address", "pay_amount"]
    )

    op.create_table(
        "crypto_chain_transfers",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("network_id", sa.String(64), sa.ForeignKey("crypto_networks.id"), nullable=False),
        sa.Column("token_id", sa.String(64), sa.ForeignKey("crypto_tokens.id"), nullable=False),
        sa.Column("tx_hash", sa.String(128), nullable=False),
        sa.Column("log_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("from_address", sa.String(128), nullable=False),
        sa.Column("to_address", sa.String(128), nullable=False),
        sa.Column("amount_raw", sa.String(96), nullable=False),
        sa.Column("amount_decimal", sa.Numeric(36, 18), nullable=False),
        sa.Column("block_number", sa.Integer(), nullable=False),
        sa.Column("block_hash", sa.String(128), nullable=True),
        sa.Column("block_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="seen"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("network_id", "tx_hash", "log_index", name="uq_crypto_transfer_log"),
    )
    for col in ["network_id", "token_id", "tx_hash", "from_address", "to_address", "block_number", "status"]:
        op.create_index(f"ix_crypto_chain_transfers_{col}", "crypto_chain_transfers", [col])

    op.create_table(
        "crypto_invoice_matches",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("invoice_id", sa.String(64), sa.ForeignKey("crypto_invoices.id"), nullable=False),
        sa.Column("transfer_id", sa.String(64), sa.ForeignKey("crypto_chain_transfers.id"), nullable=False),
        sa.Column("matched_amount", sa.Numeric(36, 18), nullable=False),
        sa.Column("match_type", sa.String(24), nullable=False, server_default="exact"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("invoice_id", "transfer_id", name="uq_crypto_invoice_transfer"),
    )
    op.create_index("ix_crypto_invoice_matches_invoice_id", "crypto_invoice_matches", ["invoice_id"])
    op.create_index("ix_crypto_invoice_matches_transfer_id", "crypto_invoice_matches", ["transfer_id"])

    op.create_table(
        "crypto_callbacks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("invoice_id", sa.String(64), sa.ForeignKey("crypto_invoices.id"), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("signature", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="6"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_crypto_callbacks_invoice_id", "crypto_callbacks", ["invoice_id"])
    op.create_index("ix_crypto_callbacks_event_type", "crypto_callbacks", ["event_type"])
    op.create_index("ix_crypto_callbacks_next_retry_at", "crypto_callbacks", ["next_retry_at"])
    op.create_index("ix_crypto_callbacks_state", "crypto_callbacks", ["state"])
    op.create_index("ix_crypto_callbacks_state_next", "crypto_callbacks", ["state", "next_retry_at"])

    op.create_table(
        "crypto_watcher_cursors",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("network_id", sa.String(64), sa.ForeignKey("crypto_networks.id"), nullable=False),
        sa.Column("token_id", sa.String(64), sa.ForeignKey("crypto_tokens.id"), nullable=False),
        sa.Column("wallet_group_hash", sa.String(128), nullable=False, server_default="default"),
        sa.Column("last_scanned_block", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_finalized_block", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lock_owner", sa.String(64), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("network_id", "token_id", "wallet_group_hash", name="uq_crypto_watcher_cursor"),
    )
    op.create_index("ix_crypto_watcher_cursors_network_id", "crypto_watcher_cursors", ["network_id"])
    op.create_index("ix_crypto_watcher_cursors_token_id", "crypto_watcher_cursors", ["token_id"])


def downgrade() -> None:
    op.drop_index("ix_crypto_watcher_cursors_token_id", table_name="crypto_watcher_cursors")
    op.drop_index("ix_crypto_watcher_cursors_network_id", table_name="crypto_watcher_cursors")
    op.drop_table("crypto_watcher_cursors")
    op.drop_index("ix_crypto_callbacks_state_next", table_name="crypto_callbacks")
    op.drop_index("ix_crypto_callbacks_state", table_name="crypto_callbacks")
    op.drop_index("ix_crypto_callbacks_next_retry_at", table_name="crypto_callbacks")
    op.drop_index("ix_crypto_callbacks_event_type", table_name="crypto_callbacks")
    op.drop_index("ix_crypto_callbacks_invoice_id", table_name="crypto_callbacks")
    op.drop_table("crypto_callbacks")
    op.drop_index("ix_crypto_invoice_matches_transfer_id", table_name="crypto_invoice_matches")
    op.drop_index("ix_crypto_invoice_matches_invoice_id", table_name="crypto_invoice_matches")
    op.drop_table("crypto_invoice_matches")
    for col in ["status", "block_number", "to_address", "from_address", "tx_hash", "token_id", "network_id"]:
        op.drop_index(f"ix_crypto_chain_transfers_{col}", table_name="crypto_chain_transfers")
    op.drop_table("crypto_chain_transfers")
    op.drop_index("ix_crypto_invoice_match", table_name="crypto_invoices")
    op.drop_index("ix_crypto_invoice_status_expires", table_name="crypto_invoices")
    for col in ["expires_at", "status", "address", "wallet_id", "token_id", "network_id", "user_id", "merchant_id", "request_id", "trans_id"]:
        op.drop_index(f"ix_crypto_invoices_{col}", table_name="crypto_invoices")
    op.drop_table("crypto_invoices")
    for col in ["status", "address", "network_id", "owner_id", "owner_type"]:
        op.drop_index(f"ix_crypto_wallets_{col}", table_name="crypto_wallets")
    op.drop_table("crypto_wallets")
    op.drop_index("ix_crypto_rpc_endpoints_status", table_name="crypto_rpc_endpoints")
    op.drop_index("ix_crypto_rpc_endpoints_network_id", table_name="crypto_rpc_endpoints")
    op.drop_table("crypto_rpc_endpoints")
    for col in ["status", "contract_address", "symbol", "network_id"]:
        op.drop_index(f"ix_crypto_tokens_{col}", table_name="crypto_tokens")
    op.drop_table("crypto_tokens")
    op.drop_index("ix_crypto_networks_status", table_name="crypto_networks")
    op.drop_index("ix_crypto_networks_chain_type", table_name="crypto_networks")
    op.drop_index("ix_crypto_networks_key", table_name="crypto_networks")
    op.drop_table("crypto_networks")
