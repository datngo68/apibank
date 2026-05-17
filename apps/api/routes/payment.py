from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import BankAccount, Order
from packages.db.session import get_session

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["payment"], include_in_schema=False)


@router.get("/pay/{code}", response_class=HTMLResponse)
async def payment_page(
    code: str, request: Request, session: AsyncSession = Depends(get_session)
) -> HTMLResponse:
    order = (
        await session.scalars(select(Order).where(Order.code == code.upper()))
    ).first()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    bank_account = await session.get(BankAccount, order.bank_account_id)
    return templates.TemplateResponse(
        request,
        "payment.html",
        {"order": order, "bank_account": bank_account},
    )


@router.get("/pay/{code}/status")
async def payment_status(
    code: str, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    order = (
        await session.scalars(select(Order).where(Order.code == code.upper()))
    ).first()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return {
        "code": order.code,
        "amount_vnd": int(order.amount_vnd),
        "status": order.status,
        "expired_at": order.expired_at.isoformat(),
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
    }
