from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.config.settings import get_settings
from packages.crypto.invoices import match_transfer, normalize_address
from packages.db.models import (
    CryptoChainTransfer,
    CryptoNetwork,
    CryptoRpcEndpoint,
    CryptoToken,
    CryptoWatcherCursor,
    utcnow,
)
from packages.security.crypto import FernetCipher

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def topic_to_address(topic: str) -> str:
    value = topic.removeprefix("0x")[-40:]
    return "0x" + value.lower()


def raw_to_decimal(raw: int | str, decimals: int) -> Decimal:
    value = int(raw, 16) if isinstance(raw, str) and raw.startswith("0x") else int(raw)
    return Decimal(value) / (Decimal(10) ** decimals)


async def rpc_call(url: str, method: str, params: list[Any]) -> Any:
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        )
        resp.raise_for_status()
        body = resp.json()
        if "error" in body:
            raise RuntimeError(body["error"])
        return body["result"]


def decrypt_rpc_url(value: str) -> str:
    keys = get_settings().fernet_keys
    if not keys:
        return value
    try:
        return FernetCipher.from_keys(keys).decrypt(value)
    except Exception:  # noqa: BLE001
        return value


async def active_rpc(session: AsyncSession, network_id: str) -> CryptoRpcEndpoint | None:
    return (
        await session.scalars(
            select(CryptoRpcEndpoint)
            .where(CryptoRpcEndpoint.network_id == network_id)
            .where(CryptoRpcEndpoint.status == "active")
            .order_by(CryptoRpcEndpoint.priority.asc())
        )
    ).first()


async def get_or_create_cursor(
    session: AsyncSession,
    *,
    network_id: str,
    token_id: str,
    start_block: int,
) -> CryptoWatcherCursor:
    cursor = (
        await session.scalars(
            select(CryptoWatcherCursor).where(
                CryptoWatcherCursor.network_id == network_id,
                CryptoWatcherCursor.token_id == token_id,
                CryptoWatcherCursor.wallet_group_hash == "default",
            )
        )
    ).first()
    if cursor is None:
        cursor = CryptoWatcherCursor(
            network_id=network_id,
            token_id=token_id,
            wallet_group_hash="default",
            last_scanned_block=start_block,
            last_finalized_block=start_block,
        )
        session.add(cursor)
        await session.flush()
    return cursor


async def scan_token_logs(
    session: AsyncSession,
    *,
    network: CryptoNetwork,
    token: CryptoToken,
    rpc_url: str,
    from_block: int,
    to_block: int,
) -> int:
    logs = await rpc_call(
        rpc_url,
        "eth_getLogs",
        [
            {
                "fromBlock": hex(from_block),
                "toBlock": hex(to_block),
                "address": token.contract_address,
                "topics": [TRANSFER_TOPIC],
            }
        ],
    )
    inserted = 0
    for log in logs:
        topics = log.get("topics") or []
        if len(topics) < 3:
            continue
        transfer = CryptoChainTransfer(
            network_id=network.id,
            token_id=token.id,
            tx_hash=log["transactionHash"].lower(),
            log_index=int(log.get("logIndex", "0x0"), 16),
            from_address=topic_to_address(topics[1]),
            to_address=normalize_address(topic_to_address(topics[2]), "evm"),
            amount_raw=str(int(log.get("data", "0x0"), 16)),
            amount_decimal=raw_to_decimal(log.get("data", "0x0"), token.decimals),
            block_number=int(log.get("blockNumber", "0x0"), 16),
            block_hash=log.get("blockHash"),
            block_time=datetime.now(UTC),
            confirmations=max(0, to_block - int(log.get("blockNumber", "0x0"), 16) + 1),
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


async def run_evm_once(
    session: AsyncSession,
    *,
    network: CryptoNetwork,
    token: CryptoToken,
    start_block: int = 0,
) -> int:
    rpc = await active_rpc(session, network.id)
    if rpc is None:
        raise RuntimeError("no active rpc endpoint")
    latest_hex = await rpc_call(rpc.url_enc, "eth_blockNumber", [])
    latest = int(latest_hex, 16)
    finalized = max(0, latest - network.min_confirmations)
    cursor = await get_or_create_cursor(
        session, network_id=network.id, token_id=token.id, start_block=start_block
    )
    if cursor.last_scanned_block >= finalized:
        return 0
    from_block = cursor.last_scanned_block + 1
    to_block = min(finalized, from_block + network.scan_batch_size - 1)
    count = await scan_token_logs(
        session,
        network=network,
        token=token,
        rpc_url=decrypt_rpc_url(rpc.url_enc),
        from_block=from_block,
        to_block=to_block,
    )
    cursor.last_scanned_block = to_block
    cursor.last_finalized_block = finalized
    cursor.updated_at = utcnow()
    rpc.last_ok_at = utcnow()
    rpc.last_error = None
    await session.flush()
    return count
