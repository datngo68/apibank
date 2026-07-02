from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.crypto.invoices import (
    cancel_invoice,
    create_invoice,
    invoice_public_payload,
    payment_qr_data_url,
)
from packages.db.models import ApiKey, CryptoInvoice, CryptoNetwork, CryptoToken
from packages.db.session import get_session
from packages.schemas.crypto import (
    CryptoInvoiceCreate,
    CryptoInvoiceListResponse,
    CryptoInvoiceRead,
    CryptoInvoiceResponse,
    CryptoNetworkRead,
    CryptoTokenRead,
)
from packages.security.audit import record_audit
from packages.security.dependencies import enforce_subscription_and_quota

router = APIRouter(prefix="/crypto", tags=["crypto"])
public_router = APIRouter(tags=["crypto-payment"], include_in_schema=False)


def _require_scope(api_key: ApiKey, scope: str) -> None:
    scopes = api_key.scopes or []
    if scope not in scopes and "admin:*" not in scopes:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="missing scope")


def _merchant_id(api_key: ApiKey) -> str:
    return api_key.user_id or api_key.owner_id or api_key.id


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


@router.get("/networks", response_model=list[CryptoNetworkRead])
async def list_networks(session: AsyncSession = Depends(get_session)) -> list[CryptoNetworkRead]:
    rows = list(
        (
            await session.scalars(
                select(CryptoNetwork)
                .where(CryptoNetwork.status == "active")
                .order_by(CryptoNetwork.key)
            )
        ).all()
    )
    return [CryptoNetworkRead.model_validate(row) for row in rows]


@router.get("/tokens", response_model=list[CryptoTokenRead])
async def list_tokens(
    network: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[CryptoTokenRead]:
    stmt = select(CryptoToken).where(CryptoToken.status == "active")
    if network:
        net = (
            await session.scalars(select(CryptoNetwork).where(CryptoNetwork.key == network.lower()))
        ).first()
        if net is None:
            return []
        stmt = stmt.where(CryptoToken.network_id == net.id)
    rows = list((await session.scalars(stmt.order_by(CryptoToken.symbol))).all())
    return [CryptoTokenRead.model_validate(row) for row in rows]


@router.post("/invoices", response_model=CryptoInvoiceResponse, status_code=status.HTTP_201_CREATED)
async def create_crypto_invoice(
    payload: CryptoInvoiceCreate,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    api_key: ApiKey = Depends(enforce_subscription_and_quota),
) -> CryptoInvoiceResponse:
    _require_scope(api_key, "crypto:write")
    try:
        invoice = await create_invoice(
            session,
            payload=payload,
            merchant_id=_merchant_id(api_key),
            user_id=api_key.user_id,
        )
    except ValueError as exc:
        text = str(exc)
        code = (
            status.HTTP_409_CONFLICT
            if "request_id reused" in text
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(status_code=code, detail=text) from exc
    await record_audit(
        session,
        actor=api_key.id,
        action="crypto.invoice.create",
        target_type="crypto_invoice",
        target_id=invoice.id,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        after={"trans_id": invoice.trans_id, "status": invoice.status},
    )
    await session.commit()
    data = invoice_public_payload(invoice, base_url=_base_url(request))
    response.status_code = status.HTTP_201_CREATED
    return CryptoInvoiceResponse(**data)


@router.get("/invoices/{trans_id}", response_model=CryptoInvoiceResponse)
async def get_crypto_invoice(
    trans_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    api_key: ApiKey = Depends(enforce_subscription_and_quota),
) -> CryptoInvoiceResponse:
    _require_scope(api_key, "crypto:read")
    invoice = (
        await session.scalars(
            select(CryptoInvoice).where(
                CryptoInvoice.trans_id == trans_id,
                CryptoInvoice.merchant_id == _merchant_id(api_key),
            )
        )
    ).first()
    if invoice is None:
        raise HTTPException(status_code=404, detail="invoice not found")
    return CryptoInvoiceResponse(**invoice_public_payload(invoice, base_url=_base_url(request)))


@router.get("/invoices", response_model=CryptoInvoiceListResponse)
async def list_crypto_invoices(
    status_filter: str | None = Query(default=None, alias="status"),
    network: str | None = None,
    token: str | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    api_key: ApiKey = Depends(enforce_subscription_and_quota),
) -> CryptoInvoiceListResponse:
    _require_scope(api_key, "crypto:read")
    stmt = select(CryptoInvoice).where(CryptoInvoice.merchant_id == _merchant_id(api_key))
    count_stmt = (
        select(func.count())
        .select_from(CryptoInvoice)
        .where(CryptoInvoice.merchant_id == _merchant_id(api_key))
    )
    if status_filter:
        stmt = stmt.where(CryptoInvoice.status == status_filter)
        count_stmt = count_stmt.where(CryptoInvoice.status == status_filter)
    if network:
        net = (
            await session.scalars(select(CryptoNetwork).where(CryptoNetwork.key == network.lower()))
        ).first()
        if net:
            stmt = stmt.where(CryptoInvoice.network_id == net.id)
            count_stmt = count_stmt.where(CryptoInvoice.network_id == net.id)
    if token:
        tok_rows = list(
            (
                await session.scalars(
                    select(CryptoToken).where(CryptoToken.symbol == token.upper())
                )
            ).all()
        )
        token_ids = [row.id for row in tok_rows]
        stmt = stmt.where(CryptoInvoice.token_id.in_(token_ids))
        count_stmt = count_stmt.where(CryptoInvoice.token_id.in_(token_ids))
    total = int((await session.execute(count_stmt)).scalar_one() or 0)
    offset = (page - 1) * limit
    rows = list(
        (
            await session.scalars(
                stmt.order_by(desc(CryptoInvoice.created_at)).limit(limit).offset(offset)
            )
        ).all()
    )
    return CryptoInvoiceListResponse(
        items=[CryptoInvoiceRead.model_validate(row) for row in rows],
        total=total,
        page=page,
        limit=limit,
        pages=(total + limit - 1) // limit,
    )


@router.post("/invoices/{trans_id}/cancel", response_model=CryptoInvoiceRead)
async def cancel_crypto_invoice(
    trans_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    api_key: ApiKey = Depends(enforce_subscription_and_quota),
) -> CryptoInvoiceRead:
    _require_scope(api_key, "crypto:write")
    try:
        invoice = await cancel_invoice(
            session, trans_id=trans_id, merchant_id=_merchant_id(api_key)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await record_audit(
        session,
        actor=api_key.id,
        action="crypto.invoice.cancel",
        target_type="crypto_invoice",
        target_id=invoice.id,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        after={"status": invoice.status},
    )
    await session.commit()
    return CryptoInvoiceRead.model_validate(invoice)


@public_router.get("/pay/usdt/{trans_id}", response_class=HTMLResponse)
async def crypto_payment_page(
    trans_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    invoice = (
        await session.scalars(select(CryptoInvoice).where(CryptoInvoice.trans_id == trans_id))
    ).first()
    if invoice is None:
        raise HTTPException(status_code=404, detail="not found")
    network = invoice.metadata_json.get("network_name") or invoice.metadata_json.get("network")
    token = invoice.metadata_json.get("token") or "USDT"
    token_address = invoice.metadata_json.get("token_address") or ""
    qr = payment_qr_data_url(invoice.address)
    html = f"""
<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Thanh toán {token}</title>
  <style>
    body{{font-family:Inter,Arial,sans-serif;background:#0b1020;color:#eef2ff;margin:0;padding:32px}}
    .card{{
      max-width:720px;margin:auto;background:#111832;border:1px solid #263152;
      border-radius:24px;padding:28px
    }}
    .row{{margin:16px 0}} .label{{color:#94a3b8;font-size:13px}}
    .value{{font-size:18px;word-break:break-all}}
    .warn{{background:#3b1d1d;color:#fecaca;padding:14px;border-radius:14px}}
    img{{width:220px;height:220px;background:white;border-radius:16px;padding:12px}}
  </style>
</head>
<body>
  <div class="card">
    <h1>Thanh toán {token}</h1>
    <div class="warn">Chỉ gửi đúng token và đúng mạng. Gửi sai mạng có thể mất tiền.</div>
    <div class="row">
      <div class="label">Số tiền chính xác</div>
      <div class="value">{invoice.pay_amount} {token}</div>
    </div>
    <div class="row"><div class="label">Mạng</div><div class="value">{network}</div></div>
    <div class="row">
      <div class="label">Địa chỉ nhận</div><div class="value">{invoice.address}</div>
    </div>
    <div class="row">
      <div class="label">Contract</div><div class="value">{token_address}</div>
    </div>
    <div class="row"><img src="{qr}" alt="QR"></div>
    <div class="row">
      <div class="label">Trạng thái</div><div class="value" id="status">{invoice.status}</div>
    </div>
    <div class="row">
      <div class="label">Hết hạn</div><div class="value">{invoice.expires_at.isoformat()}</div>
    </div>
  </div>
  <script>
    setInterval(async () => {{
      const r = await fetch('/pay/usdt/{invoice.trans_id}/status');
      if (r.ok) {{
        const j = await r.json();
        document.getElementById('status').textContent = j.status;
      }}
    }}, 5000);
  </script>
</body>
</html>
"""
    return HTMLResponse(html)


@public_router.get("/pay/usdt/{trans_id}/status")
async def crypto_payment_status(
    trans_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    invoice = (
        await session.scalars(select(CryptoInvoice).where(CryptoInvoice.trans_id == trans_id))
    ).first()
    if invoice is None:
        raise HTTPException(status_code=404, detail="not found")
    return {
        "trans_id": invoice.trans_id,
        "status": invoice.status,
        "pay_amount": str(invoice.pay_amount),
        "received_amount": str(invoice.received_amount),
        "expires_at": invoice.expires_at.isoformat(),
        "paid_at": invoice.paid_at.isoformat() if invoice.paid_at else None,
    }
