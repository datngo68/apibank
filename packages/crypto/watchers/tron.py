from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.crypto.invoices import match_transfer, normalize_address
from packages.db.models import CryptoChainTransfer, CryptoNetwork, CryptoToken


def raw_to_decimal(raw: int | str, decimals: int) -> Decimal:
    return Decimal(int(raw)) / (Decimal(10) ** decimals)


async def fetch_trc20_events(
    api_base: str,
    *,
    contract: str,
    since_timestamp: int | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"event_name": "Transfer", "limit": limit, "only_confirmed": "true"}
    if since_timestamp is not None:
        params["min_block_timestamp"] = since_timestamp
    url = f"{api_base.rstrip('/')}/v1/contracts/{contract}/events"
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return list(resp.json().get("data") or [])


async def ingest_tron_events(
    session: AsyncSession,
    *,
    network: CryptoNetwork,
    token: CryptoToken,
    events: list[dict[str, Any]],
) -> int:
    inserted = 0
    for event in events:
        result = event.get("result") or {}
        tx_hash = str(event.get("transaction_id") or event.get("transaction") or "").lower()
        if not tx_hash:
            continue
        raw_amount = result.get("value") or result.get("_value") or "0"
        transfer = CryptoChainTransfer(
            network_id=network.id,
            token_id=token.id,
            tx_hash=tx_hash,
            log_index=int(event.get("event_index") or event.get("log_index") or 0),
            from_address=normalize_address(
                str(result.get("from") or result.get("_from") or ""), "tron"
            ),
            to_address=normalize_address(str(result.get("to") or result.get("_to") or ""), "tron"),
            amount_raw=str(raw_amount),
            amount_decimal=raw_to_decimal(raw_amount, token.decimals),
            block_number=int(event.get("block_number") or 0),
            block_hash=None,
            block_time=None,
            confirmations=network.min_confirmations,
            status="confirmed",
        )
        session.add(transfer)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            continue
        inserted += 1
        await match_transfer(session, transfer)
    return inserted
