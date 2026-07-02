from __future__ import annotations

import base64
import io
import secrets
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Any

import qrcode
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.crypto.callbacks import enqueue_invoice_callback
from packages.db.models import (
    CryptoChainTransfer,
    CryptoInvoice,
    CryptoInvoiceMatch,
    CryptoNetwork,
    CryptoToken,
    CryptoWallet,
    utcnow,
)
from packages.schemas.crypto import CryptoInvoiceCreate
from packages.webhook import encrypt_webhook_secret, validate_webhook_url

TERMINAL_STATUSES = {"completed", "overpaid", "canceled", "failed_review"}
WAITING_STATUSES = {"waiting", "partial"}


def normalize_address(address: str, chain_type: str = "evm") -> str:
    value = address.strip()
    return value.lower() if chain_type == "evm" else value


def generate_trans_id() -> str:
    return "TX" + utcnow().strftime("%y%m%d") + secrets.token_hex(5).upper()


def payment_qr_data_url(content: str) -> str:
    image = qrcode.make(content)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def _suffix_amount(amount: Decimal, precision: int) -> Decimal:
    if precision <= 0:
        return amount
    unit = Decimal(1).scaleb(-precision)
    suffix = Decimal(secrets.randbelow(10**precision - 1) + 1).scaleb(-precision)
    quantized = amount.quantize(unit, rounding=ROUND_DOWN)
    return quantized + suffix


async def get_network_token(
    session: AsyncSession,
    *,
    network_key: str,
    token_symbol: str,
) -> tuple[CryptoNetwork, CryptoToken]:
    network = (
        await session.scalars(
            select(CryptoNetwork)
            .where(CryptoNetwork.key == network_key.lower())
            .where(CryptoNetwork.status == "active")
        )
    ).first()
    if network is None:
        raise ValueError("network not active")
    token = (
        await session.scalars(
            select(CryptoToken)
            .where(CryptoToken.network_id == network.id)
            .where(CryptoToken.symbol == token_symbol.upper())
            .where(CryptoToken.status == "active")
        )
    ).first()
    if token is None:
        raise ValueError("token not active on network")
    return network, token


async def choose_wallet(
    session: AsyncSession,
    *,
    network: CryptoNetwork,
    address: str | None,
    merchant_id: str,
) -> CryptoWallet:
    if address:
        normalized = normalize_address(address, network.chain_type)
        wallet = (
            await session.scalars(
                select(CryptoWallet).where(
                    CryptoWallet.network_id == network.id,
                    CryptoWallet.address == normalized,
                    CryptoWallet.status == "active",
                )
            )
        ).first()
        if wallet is None:
            wallet = CryptoWallet(
                owner_type="merchant",
                owner_id=merchant_id,
                network_id=network.id,
                address=normalized,
                label="merchant supplied",
                status="active",
            )
            session.add(wallet)
            await session.flush()
        return wallet
    wallet = (
        await session.scalars(
            select(CryptoWallet)
            .where(CryptoWallet.network_id == network.id)
            .where(CryptoWallet.status == "active")
            .where(CryptoWallet.active_invoice_count < CryptoWallet.max_active_invoices)
            .order_by(CryptoWallet.active_invoice_count.asc(), CryptoWallet.created_at.asc())
        )
    ).first()
    if wallet is None:
        raise ValueError("no active crypto wallet for network")
    return wallet


async def create_invoice(
    session: AsyncSession,
    *,
    payload: CryptoInvoiceCreate,
    merchant_id: str,
    user_id: str | None,
) -> CryptoInvoice:
    existing = (
        await session.scalars(
            select(CryptoInvoice).where(
                CryptoInvoice.merchant_id == merchant_id,
                CryptoInvoice.request_id == payload.request_id,
            )
        )
    ).first()
    if existing is not None:
        if (
            Decimal(existing.requested_amount) != payload.amount
            or existing.name != payload.name
            or existing.metadata_json.get("network") != payload.network.lower()
            or existing.metadata_json.get("token") != payload.token.upper()
        ):
            raise ValueError("request_id reused with different payload")
        return existing

    network, token = await get_network_token(
        session, network_key=payload.network, token_symbol=payload.token
    )
    amount = payload.amount
    if amount < Decimal(token.min_invoice_amount) or amount > Decimal(token.max_invoice_amount):
        raise ValueError("amount outside token limits")
    wallet = await choose_wallet(
        session, network=network, address=payload.address, merchant_id=merchant_id
    )
    pay_amount = _suffix_amount(amount, token.dust_precision) if payload.address is None else amount
    callback_url = str(payload.callback_url) if payload.callback_url else None
    if callback_url:
        validate_webhook_url(callback_url)
    invoice = CryptoInvoice(
        trans_id=generate_trans_id(),
        request_id=payload.request_id,
        merchant_id=merchant_id,
        user_id=user_id,
        name=payload.name,
        description=payload.description,
        network_id=network.id,
        token_id=token.id,
        wallet_id=wallet.id,
        address=wallet.address,
        requested_amount=amount,
        pay_amount=pay_amount,
        received_amount=Decimal(0),
        currency_amount_vnd=payload.currency_amount_vnd,
        fx_rate=payload.fx_rate,
        fx_source=payload.fx_source,
        fx_locked_at=utcnow() if payload.fx_rate else None,
        status="waiting",
        expires_at=utcnow() + timedelta(minutes=payload.expire_minutes),
        callback_url=callback_url,
        success_url=str(payload.success_url) if payload.success_url else None,
        cancel_url=str(payload.cancel_url) if payload.cancel_url else None,
        webhook_secret_enc=encrypt_webhook_secret(payload.webhook_secret)
        if payload.webhook_secret
        else None,
        metadata_json={
            "network": network.key,
            "network_name": network.name,
            "token": token.symbol,
            "token_address": token.contract_address,
            "expire_minutes": payload.expire_minutes,
            "mode": "merchant_wallet" if payload.address else "platform_wallet",
            **payload.metadata,
        },
    )
    session.add(invoice)
    wallet.active_invoice_count += 1
    await session.flush()
    return invoice


async def cancel_invoice(
    session: AsyncSession,
    *,
    trans_id: str,
    merchant_id: str | None = None,
) -> CryptoInvoice:
    stmt = select(CryptoInvoice).where(CryptoInvoice.trans_id == trans_id)
    if merchant_id is not None:
        stmt = stmt.where(CryptoInvoice.merchant_id == merchant_id)
    invoice = (await session.scalars(stmt)).first()
    if invoice is None:
        raise ValueError("invoice not found")
    if invoice.status not in WAITING_STATUSES:
        raise ValueError("invoice cannot be canceled")
    invoice.status = "canceled"
    invoice.canceled_at = utcnow()
    await release_wallet_slot(session, invoice)
    await enqueue_invoice_callback(session, invoice=invoice, event_type="crypto.invoice.canceled")
    await session.flush()
    return invoice


async def release_wallet_slot(session: AsyncSession, invoice: CryptoInvoice) -> None:
    wallet = await session.get(CryptoWallet, invoice.wallet_id)
    if wallet is not None and wallet.active_invoice_count > 0:
        wallet.active_invoice_count -= 1


async def expire_due_invoices(session: AsyncSession, *, limit: int = 500) -> int:
    invoices = list(
        (
            await session.scalars(
                select(CryptoInvoice)
                .where(CryptoInvoice.status.in_(list(WAITING_STATUSES)))
                .where(CryptoInvoice.expires_at < utcnow())
                .limit(limit)
            )
        ).all()
    )
    for invoice in invoices:
        invoice.status = "expired"
        await release_wallet_slot(session, invoice)
        await enqueue_invoice_callback(
            session, invoice=invoice, event_type="crypto.invoice.expired"
        )
    await session.flush()
    return len(invoices)


async def match_transfer(
    session: AsyncSession, transfer: CryptoChainTransfer
) -> CryptoInvoice | None:
    invoice = (
        await session.scalars(
            select(CryptoInvoice)
            .where(CryptoInvoice.network_id == transfer.network_id)
            .where(CryptoInvoice.token_id == transfer.token_id)
            .where(CryptoInvoice.address == transfer.to_address)
            .where(CryptoInvoice.status.in_(list(WAITING_STATUSES)))
            .where(CryptoInvoice.created_at <= (transfer.block_time or utcnow()))
            .where(CryptoInvoice.expires_at >= (transfer.block_time or utcnow()))
            .where(CryptoInvoice.pay_amount == transfer.amount_decimal)
            .order_by(CryptoInvoice.created_at.asc())
        )
    ).first()
    if invoice is None:
        return None
    existing_match = (
        await session.scalars(
            select(CryptoInvoiceMatch).where(
                CryptoInvoiceMatch.invoice_id == invoice.id,
                CryptoInvoiceMatch.transfer_id == transfer.id,
            )
        )
    ).first()
    if existing_match is not None:
        return invoice
    session.add(
        CryptoInvoiceMatch(
            invoice_id=invoice.id,
            transfer_id=transfer.id,
            matched_amount=transfer.amount_decimal,
            match_type="exact",
        )
    )
    transfer.status = "matched"
    invoice.received_amount = Decimal(invoice.received_amount) + Decimal(transfer.amount_decimal)
    invoice.from_address = transfer.from_address
    invoice.transaction_id = transfer.tx_hash
    invoice.confirmations = transfer.confirmations
    if Decimal(invoice.received_amount) >= Decimal(invoice.pay_amount):
        invoice.status = "completed"
        invoice.paid_at = utcnow()
        await release_wallet_slot(session, invoice)
        from packages.crypto.topup import credit_wallet_for_crypto_invoice

        await credit_wallet_for_crypto_invoice(session, invoice)
        await enqueue_invoice_callback(
            session, invoice=invoice, event_type="crypto.invoice.completed"
        )
    else:
        invoice.status = "partial"
        await enqueue_invoice_callback(
            session, invoice=invoice, event_type="crypto.invoice.partial"
        )
    await session.flush()
    return invoice


async def invoice_total(session: AsyncSession, *, merchant_id: str | None = None) -> int:
    stmt = select(func.count()).select_from(CryptoInvoice)
    if merchant_id is not None:
        stmt = stmt.where(CryptoInvoice.merchant_id == merchant_id)
    return int((await session.execute(stmt)).scalar_one() or 0)


def invoice_payment_url(base_url: str, invoice: CryptoInvoice) -> str:
    return f"{base_url.rstrip('/')}/pay/usdt/{invoice.trans_id}"


def invoice_public_payload(invoice: CryptoInvoice, *, base_url: str) -> dict[str, Any]:
    qr_content = invoice.address
    return {
        "data": invoice,
        "status": "success",
        "msg": "ok",
        "url_payment": invoice_payment_url(base_url, invoice),
        "qr_content": qr_content,
        "qrcode": payment_qr_data_url(qr_content),
    }
