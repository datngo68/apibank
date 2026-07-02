from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.crypto.invoices import match_transfer
from packages.db.models import (
    CryptoChainTransfer,
    CryptoInvoice,
    CryptoNetwork,
    CryptoToken,
    CryptoWatcherCursor,
)


async def reconcile_invoice(session: AsyncSession, invoice: CryptoInvoice) -> int:
    transfers = list(
        (
            await session.scalars(
                select(CryptoChainTransfer).where(
                    CryptoChainTransfer.network_id == invoice.network_id,
                    CryptoChainTransfer.token_id == invoice.token_id,
                    CryptoChainTransfer.to_address == invoice.address,
                    CryptoChainTransfer.amount_decimal == invoice.pay_amount,
                    CryptoChainTransfer.status.in_(["seen", "confirmed"]),
                )
            )
        ).all()
    )
    matched = 0
    for transfer in transfers:
        if await match_transfer(session, transfer):
            matched += 1
    return matched


async def reconcile_tx_hash(session: AsyncSession, tx_hash: str) -> int:
    transfers = list(
        (
            await session.scalars(
                select(CryptoChainTransfer).where(CryptoChainTransfer.tx_hash == tx_hash.lower())
            )
        ).all()
    )
    matched = 0
    for transfer in transfers:
        if await match_transfer(session, transfer):
            matched += 1
    return matched


async def watcher_health(session: AsyncSession) -> list[dict[str, object]]:
    rows = list((await session.scalars(select(CryptoWatcherCursor))).all())
    health: list[dict[str, object]] = []
    for cursor in rows:
        network = await session.get(CryptoNetwork, cursor.network_id)
        token = await session.get(CryptoToken, cursor.token_id)
        latest = cursor.last_finalized_block
        health.append(
            {
                "network_id": cursor.network_id,
                "network": network.key if network else None,
                "token_id": cursor.token_id,
                "token": token.symbol if token else None,
                "wallet_group_hash": cursor.wallet_group_hash,
                "last_scanned_block": cursor.last_scanned_block,
                "last_finalized_block": cursor.last_finalized_block,
                "lag_blocks": max(0, latest - cursor.last_scanned_block),
                "locked_until": cursor.locked_until,
            }
        )
    return health
