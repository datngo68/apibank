from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from packages.billing import wallet
from packages.db.models import CryptoInvoice


async def credit_wallet_for_crypto_invoice(session: AsyncSession, invoice: CryptoInvoice) -> bool:
    if invoice.status not in {"completed", "overpaid"}:
        return False
    if not invoice.user_id or invoice.currency_amount_vnd is None:
        return False
    tx = await wallet.credit(
        session,
        user_id=invoice.user_id,
        amount_vnd=Decimal(invoice.currency_amount_vnd),
        idempotency_key=f"crypto-topup:{invoice.id}",
        ref_kind="crypto_invoice",
        ref_id=invoice.id,
        note=f"Topup crypto {invoice.trans_id}",
        created_by="system:crypto",
    )
    return tx.id is not None
