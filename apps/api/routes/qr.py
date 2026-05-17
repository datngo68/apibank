"""QR endpoint cho topup order — generate VietQR EMVCo payload local + render PNG.

Trước đây gọi img.vietqr.io (service ngoài) — không ổn định khi rate-limit / 502.
Giờ tự sinh payload đúng chuẩn EMVCo VietQR (NAPAS BIN), tuyệt đối không phụ thuộc
mạng ngoài. App banking VN (MB, VCB, BIDV, ACB...) đều scan được.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import BankAccount, Order
from packages.db.session import get_session
from packages.qr.vietqr import BANK_BIN, generate_qr_png, generate_vietqr_payload

router = APIRouter(tags=["public"])


def _resolve_bin(bank_code: str) -> str | None:
    return BANK_BIN.get(bank_code.upper())


@router.get("/qr/{order_id}.png")
async def order_qr_png(
    order_id: str, session: AsyncSession = Depends(get_session)
) -> Response:
    order = await session.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="order not found")
    bank_account = await session.get(BankAccount, order.bank_account_id)
    if bank_account is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="bank account missing"
        )

    bin_code = _resolve_bin(bank_account.bank_code)
    if bin_code is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unsupported bank code {bank_account.bank_code}",
        )

    payload = generate_vietqr_payload(
        bank_bin=bin_code,
        account_no=bank_account.account_no,
        amount_vnd=int(order.amount_vnd),
        content=order.code,
    )
    png = generate_qr_png(payload)
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )
