from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class CryptoNetworkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    key: str
    name: str
    chain_type: str
    chain_id: int | None
    native_symbol: str | None
    min_confirmations: int
    finality_blocks: int
    scan_batch_size: int
    status: str


class CryptoTokenRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    network_id: str
    symbol: str
    name: str
    contract_address: str
    decimals: int
    min_invoice_amount: Decimal
    max_invoice_amount: Decimal
    dust_precision: int
    status: str


class CryptoWalletRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    owner_type: str
    owner_id: str | None
    network_id: str
    address: str
    label: str | None
    status: str
    max_active_invoices: int
    active_invoice_count: int


class CryptoInvoiceCreate(BaseModel):
    request_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    amount: Decimal = Field(gt=0)
    token: str = Field(default="USDT", min_length=2, max_length=16)
    network: str = Field(min_length=2, max_length=32)
    address: str | None = Field(default=None, min_length=16, max_length=128)
    expire_minutes: int = Field(default=30, ge=1, le=1440)
    callback_url: HttpUrl | None = None
    success_url: HttpUrl | None = None
    cancel_url: HttpUrl | None = None
    webhook_secret: str | None = Field(default=None, min_length=16, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)
    currency_amount_vnd: Decimal | None = Field(default=None, ge=0)
    fx_rate: Decimal | None = Field(default=None, gt=0)
    fx_source: str | None = Field(default=None, max_length=64)


class CryptoInvoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    trans_id: str
    request_id: str
    merchant_id: str
    user_id: str | None
    name: str
    description: str | None
    network_id: str
    token_id: str
    wallet_id: str
    address: str
    requested_amount: Decimal
    pay_amount: Decimal
    received_amount: Decimal
    currency_amount_vnd: Decimal | None
    fx_rate: Decimal | None
    fx_source: str | None
    status: str
    expires_at: datetime
    paid_at: datetime | None
    canceled_at: datetime | None
    callback_url: str | None
    success_url: str | None
    cancel_url: str | None
    from_address: str | None
    transaction_id: str | None
    confirmations: int
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class CryptoInvoiceResponse(BaseModel):
    data: CryptoInvoiceRead
    status: str = "success"
    msg: str = "ok"
    url_payment: str | None = None
    qr_content: str | None = None
    qrcode: str | None = None


class CryptoInvoiceListResponse(BaseModel):
    items: list[CryptoInvoiceRead]
    total: int
    page: int
    limit: int
    pages: int


class CryptoChainTransferRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    network_id: str
    token_id: str
    tx_hash: str
    log_index: int
    from_address: str
    to_address: str
    amount_raw: str
    amount_decimal: Decimal
    block_number: int
    block_hash: str | None
    block_time: datetime | None
    confirmations: int
    status: str


class CryptoRpcEndpointCreate(BaseModel):
    network: str = Field(min_length=2, max_length=32)
    url: str = Field(min_length=8, max_length=2000)
    provider: str = Field(min_length=1, max_length=64)
    priority: int = Field(default=100, ge=1, le=10000)
    rate_limit_per_sec: int = Field(default=5, ge=1, le=1000)


class CryptoWalletCreate(BaseModel):
    network: str = Field(min_length=2, max_length=32)
    address: str = Field(min_length=16, max_length=128)
    owner_type: str = Field(default="system", max_length=16)
    owner_id: str | None = Field(default=None, max_length=64)
    label: str | None = Field(default=None, max_length=128)
    max_active_invoices: int = Field(default=100, ge=1, le=100000)


class CryptoNetworkCreate(BaseModel):
    key: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=2, max_length=128)
    chain_type: str = Field(pattern="^(evm|tron)$")
    chain_id: int | None = None
    native_symbol: str | None = Field(default=None, max_length=16)
    min_confirmations: int = Field(default=12, ge=1, le=1000)
    finality_blocks: int = Field(default=64, ge=1, le=10000)
    scan_batch_size: int = Field(default=1000, ge=1, le=100000)


class CryptoTokenCreate(BaseModel):
    network: str = Field(min_length=2, max_length=32)
    symbol: str = Field(min_length=2, max_length=16)
    name: str = Field(min_length=2, max_length=128)
    contract_address: str = Field(min_length=16, max_length=128)
    decimals: int = Field(default=18, ge=0, le=36)
    min_invoice_amount: Decimal = Field(default=Decimal("1"), gt=0)
    max_invoice_amount: Decimal = Field(default=Decimal("100000"), gt=0)
    dust_precision: int = Field(default=6, ge=0, le=18)


class CryptoWatcherHealth(BaseModel):
    network_id: str
    token_id: str
    wallet_group_hash: str
    last_scanned_block: int
    last_finalized_block: int
    lag_blocks: int
    locked_until: datetime | None


class CryptoReconcileRequest(BaseModel):
    network: str
    token: str | None = None
    tx_hash: str | None = None
    invoice_id: str | None = None
    block_from: int | None = None
    block_to: int | None = None
