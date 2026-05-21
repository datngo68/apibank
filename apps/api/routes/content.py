"""Public content endpoints — FAQ, changelog, legal current.

Trả markdown content cho FE render. Không cần auth.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import LegalVersion
from packages.db.session import get_session

router = APIRouter(prefix="/api/v1/content", tags=["content"])


_FAQ_ITEMS = [
    {
        "q": "Làm sao để bắt đầu nhận thanh toán?",
        "a": "1) Liên kết tài khoản ngân hàng. 2) Tạo API key. 3) Gọi POST /v1/orders.",
    },
    {
        "q": "Tôi quên mật khẩu phải làm gì?",
        "a": "Vào /forgot, nhập email; check inbox để reset.",
    },
    {
        "q": "Làm sao để rút tiền khỏi ví?",
        "a": "Vào Wallet → Withdraw, chọn bank account đã verify, nhập số tiền.",
    },
    {
        "q": "Webhook không chạy?",
        "a": "Kiểm tra IP allowlist, signature secret, và xem Webhook Attempts trong dashboard.",
    },
    {
        "q": "Sandbox/test mode là gì?",
        "a": "Khi tạo API key, chọn mode='test'. Order tạo bằng test key sẽ không charge thật.",
    },
]


@router.get("/faq")
async def faq() -> list[dict[str, str]]:
    return _FAQ_ITEMS


@router.get("/changelog")
async def changelog() -> list[dict[str, Any]]:
    return [
        {
            "version": "0.4.0",
            "date": "2026-05-21",
            "highlights": [
                "Admin orders/transactions/webhooks UI + DLQ replay",
                "Subscriptions admin (cancel/extend/change-plan/refund)",
                "User: change email, GDPR export, withdraw, support ticket",
                "Multi-admin role matrix (super_admin/support/finance)",
                "Notification retry + DLQ; webhook jitter + per-host cap",
                "CAPTCHA cho register/forgot, IP blocklist, maintenance mode",
            ],
        },
        {
            "version": "0.3.0",
            "date": "2026-05-21",
            "highlights": [
                "Admin api-keys + usage analytics + revenue dashboard",
            ],
        },
    ]


@router.get("/legal/{kind}")
async def current_legal(
    kind: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    if kind not in ("terms", "privacy"):
        raise HTTPException(status_code=400, detail="kind invalid")
    row = (
        await session.scalars(
            select(LegalVersion)
            .where(LegalVersion.kind == kind)
            .order_by(desc(LegalVersion.effective_at))
            .limit(1)
        )
    ).first()
    if row is None:
        return {"kind": kind, "version": None, "content_md": ""}
    return {
        "kind": row.kind,
        "version": row.version,
        "effective_at": row.effective_at.isoformat(),
        "content_md": row.content_md,
    }


__all__ = ["router"]
