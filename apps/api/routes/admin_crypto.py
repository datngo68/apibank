from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.config.settings import get_settings
from packages.crypto.reconcile import reconcile_invoice, reconcile_tx_hash, watcher_health
from packages.db.models import (
    CryptoInvoice,
    CryptoNetwork,
    CryptoRpcEndpoint,
    CryptoToken,
    CryptoWallet,
    User,
)
from packages.db.session import get_session
from packages.schemas.auth import GenericMessage
from packages.schemas.crypto import (
    CryptoNetworkCreate,
    CryptoNetworkRead,
    CryptoReconcileRequest,
    CryptoRpcEndpointCreate,
    CryptoTokenCreate,
    CryptoTokenRead,
    CryptoWalletCreate,
    CryptoWalletRead,
)
from packages.security.audit import record_audit
from packages.security.crypto import FernetCipher
from packages.security.user_auth import current_admin_user

router = APIRouter(prefix="/api/v1/admin/crypto", tags=["admin-crypto"])


def _cipher() -> FernetCipher | None:
    keys = get_settings().fernet_keys
    return FernetCipher.from_keys(keys) if keys else None


def _encrypt_secret(value: str) -> str:
    cipher = _cipher()
    return cipher.encrypt(value) if cipher else value


@router.get("/networks", response_model=list[CryptoNetworkRead])
async def admin_list_networks(
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> list[CryptoNetworkRead]:
    rows = list((await session.scalars(select(CryptoNetwork).order_by(CryptoNetwork.key))).all())
    return [CryptoNetworkRead.model_validate(row) for row in rows]


@router.post("/networks", response_model=CryptoNetworkRead)
async def admin_create_network(
    payload: CryptoNetworkCreate,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> CryptoNetworkRead:
    network = CryptoNetwork(**payload.model_dump())
    network.key = network.key.lower()
    session.add(network)
    await session.flush()
    await record_audit(
        session,
        actor=actor.id,
        action="admin.crypto.network.create",
        target_type="crypto_network",
        target_id=network.id,
        ip=request.client.host if request.client else None,
        after=payload.model_dump(mode="json"),
    )
    await session.commit()
    return CryptoNetworkRead.model_validate(network)


@router.post("/tokens", response_model=CryptoTokenRead)
async def admin_create_token(
    payload: CryptoTokenCreate,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> CryptoTokenRead:
    network = (
        await session.scalars(
            select(CryptoNetwork).where(CryptoNetwork.key == payload.network.lower())
        )
    ).first()
    if network is None:
        raise HTTPException(status_code=404, detail="network not found")
    token = CryptoToken(
        network_id=network.id,
        symbol=payload.symbol.upper(),
        name=payload.name,
        contract_address=payload.contract_address.lower()
        if network.chain_type == "evm"
        else payload.contract_address,
        decimals=payload.decimals,
        min_invoice_amount=payload.min_invoice_amount,
        max_invoice_amount=payload.max_invoice_amount,
        dust_precision=payload.dust_precision,
    )
    session.add(token)
    await session.flush()
    await record_audit(
        session,
        actor=actor.id,
        action="admin.crypto.token.create",
        target_type="crypto_token",
        target_id=token.id,
        ip=request.client.host if request.client else None,
        after=payload.model_dump(mode="json"),
    )
    await session.commit()
    return CryptoTokenRead.model_validate(token)


@router.post("/wallets", response_model=CryptoWalletRead)
async def admin_create_wallet(
    payload: CryptoWalletCreate,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> CryptoWalletRead:
    network = (
        await session.scalars(
            select(CryptoNetwork).where(CryptoNetwork.key == payload.network.lower())
        )
    ).first()
    if network is None:
        raise HTTPException(status_code=404, detail="network not found")
    address = payload.address.lower() if network.chain_type == "evm" else payload.address
    wallet = CryptoWallet(
        owner_type=payload.owner_type,
        owner_id=payload.owner_id,
        network_id=network.id,
        address=address,
        label=payload.label,
        max_active_invoices=payload.max_active_invoices,
    )
    session.add(wallet)
    await session.flush()
    await record_audit(
        session,
        actor=actor.id,
        action="admin.crypto.wallet.create",
        target_type="crypto_wallet",
        target_id=wallet.id,
        ip=request.client.host if request.client else None,
        after=payload.model_dump(mode="json"),
    )
    await session.commit()
    return CryptoWalletRead.model_validate(wallet)


@router.post("/rpc-endpoints", response_model=GenericMessage)
async def admin_create_rpc_endpoint(
    payload: CryptoRpcEndpointCreate,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    network = (
        await session.scalars(
            select(CryptoNetwork).where(CryptoNetwork.key == payload.network.lower())
        )
    ).first()
    if network is None:
        raise HTTPException(status_code=404, detail="network not found")
    endpoint = CryptoRpcEndpoint(
        network_id=network.id,
        url_enc=_encrypt_secret(payload.url),
        provider=payload.provider,
        priority=payload.priority,
        rate_limit_per_sec=payload.rate_limit_per_sec,
    )
    session.add(endpoint)
    await session.flush()
    await record_audit(
        session,
        actor=actor.id,
        action="admin.crypto.rpc.create",
        target_type="crypto_rpc_endpoint",
        target_id=endpoint.id,
        ip=request.client.host if request.client else None,
        after={"network": payload.network, "provider": payload.provider},
    )
    await session.commit()
    return GenericMessage(message="created")


@router.get("/invoices")
async def admin_list_crypto_invoices(
    limit: int = 100,
    offset: int = 0,
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    rows = list(
        (
            await session.scalars(
                select(CryptoInvoice)
                .order_by(desc(CryptoInvoice.created_at))
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "trans_id": row.trans_id,
                "request_id": row.request_id,
                "merchant_id": row.merchant_id,
                "status": row.status,
                "pay_amount": str(row.pay_amount),
                "received_amount": str(row.received_amount),
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ],
        "limit": limit,
        "offset": offset,
    }


@router.get("/watcher-health")
async def admin_watcher_health(
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    return await watcher_health(session)


@router.post("/reconcile")
async def admin_reconcile(
    payload: CryptoReconcileRequest,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    matched = 0
    if payload.invoice_id:
        invoice = await session.get(CryptoInvoice, payload.invoice_id)
        if invoice is None:
            raise HTTPException(status_code=404, detail="invoice not found")
        matched += await reconcile_invoice(session, invoice)
    if payload.tx_hash:
        matched += await reconcile_tx_hash(session, payload.tx_hash)
    await record_audit(
        session,
        actor=actor.id,
        action="admin.crypto.reconcile",
        target_type="crypto_reconcile",
        target_id=payload.invoice_id or payload.tx_hash or "range",
        ip=request.client.host if request.client else None,
        after={"matched": matched, **payload.model_dump(mode="json")},
    )
    await session.commit()
    return {"matched": matched}


@router.post("/invoices/{invoice_id}/review/complete", response_model=GenericMessage)
async def admin_force_complete_invoice(
    invoice_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    invoice = await session.get(CryptoInvoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="invoice not found")
    before = {"status": invoice.status}
    invoice.status = "completed"
    await record_audit(
        session,
        actor=actor.id,
        action="admin.crypto.invoice.force_complete",
        target_type="crypto_invoice",
        target_id=invoice.id,
        ip=request.client.host if request.client else None,
        before=before,
        after={"status": invoice.status},
    )
    await session.commit()
    return GenericMessage(message="completed")
