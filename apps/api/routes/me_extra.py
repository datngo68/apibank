"""User self-service extras (Phase 4) — security/api/billing/wallet/bank/notif/support.

Mỗi endpoint require cookie session. Mọi mutation ghi SecurityEvent + audit log
khi liên quan đến security.
"""

from __future__ import annotations

import csv
import io
import logging
import secrets
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.config.settings import get_settings
from packages.db.models import (
    ApiKey,
    BankAccount,
    BillingProfile,
    EmailToken,
    Invoice,
    Plan,
    SecurityEvent,
    Subscription,
    SupportTicket,
    TicketMessage,
    TwoFactor,
    User,
    WalletTransaction,
    Webhook,
    WithdrawalRequest,
)
from packages.db.session import get_session
from packages.notifications import email as email_pkg
from packages.schemas.auth import GenericMessage
from packages.security.api_keys import generate_api_key, hash_api_key
from packages.security.email_tokens import (
    KIND_CHANGE_EMAIL,
    consume_email_token,
    issue_email_token,
)
from packages.security.passwords import hash_password, verify_password
from packages.security.sessions import revoke_all_sessions
from packages.security.tokens import generate_token, hash_token
from packages.security.user_auth import current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/me", tags=["me-extra"])


def _record_security_event(
    session: AsyncSession,
    *,
    user: User,
    kind: str,
    request: Request,
    detail: dict[str, Any] | None = None,
) -> None:
    session.add(
        SecurityEvent(
            user_id=user.id,
            kind=kind,
            ip=request.client.host if request.client else None,
            user_agent=(request.headers.get("user-agent") or "")[:512] or None,
            detail=detail,
        )
    )


# ---------------------------------------------------------------------------
# SECURITY: change email + delete + data export + 2FA recovery + event log
# ---------------------------------------------------------------------------


@router.post("/account/change-email-request", response_model=GenericMessage)
async def change_email_request(
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    new_email: str = Query(..., min_length=3, max_length=255),
    current_password: str = Query(..., min_length=1, max_length=128),
) -> GenericMessage:
    if not verify_password(current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="invalid password")
    new_email = new_email.lower().strip()
    if new_email == user.email:
        raise HTTPException(status_code=400, detail="same email")
    existing = (
        await session.scalars(select(User).where(User.email == new_email))
    ).first()
    if existing is not None:
        # Anti-enumeration: vẫn trả ok generic.
        return GenericMessage(message="check email to confirm")
    raw, record = await issue_email_token(session, user, KIND_CHANGE_EMAIL)
    record.token_hash = hash_token(f"{raw}|{new_email}")  # bind email vào token
    _record_security_event(
        session, user=user, kind="email_change_request", request=request,
        detail={"new_email": new_email},
    )
    await session.commit()
    await email_pkg.send_email(
        to=new_email,
        subject="APIBank · Xác minh email mới",
        body=(
            f"Bạn yêu cầu đổi email APIBank sang {new_email}.\n"
            f"Token: {raw}\n"
            f"Link: /change-email?token={raw}&email={new_email}\n"
            "Hết hạn 2 giờ. Bỏ qua nếu không phải bạn."
        ),
        session=session,
    )
    return GenericMessage(message="check email to confirm")


@router.post("/account/change-email-confirm", response_model=GenericMessage)
async def change_email_confirm(
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    token: str = Query(..., min_length=10, max_length=128),
    new_email: str = Query(..., min_length=3, max_length=255),
) -> GenericMessage:
    new_email = new_email.lower().strip()
    digest = hash_token(f"{token}|{new_email}")
    record = (
        await session.scalars(
            select(EmailToken)
            .where(EmailToken.token_hash == digest)
            .where(EmailToken.kind == KIND_CHANGE_EMAIL)
            .where(EmailToken.user_id == user.id)
        )
    ).first()
    now = datetime.now(UTC)
    if record is None or record.used_at is not None:
        raise HTTPException(status_code=400, detail="invalid token")
    expires = record.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires < now:
        raise HTTPException(status_code=400, detail="expired")
    # Conflict?
    existing = (
        await session.scalars(select(User).where(User.email == new_email))
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="email taken")
    old_email = user.email
    user.email = new_email
    user.email_verified_at = now
    record.used_at = now
    await revoke_all_sessions(session, user.id)
    _record_security_event(
        session, user=user, kind="email_change_confirm", request=request,
        detail={"old": old_email, "new": new_email},
    )
    await session.commit()
    return GenericMessage(message="email changed; please login again")


@router.delete("/account", response_model=GenericMessage)
async def delete_my_account(
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    current_password: str = Query(..., min_length=1, max_length=128),
) -> GenericMessage:
    """Soft delete + revoke all sessions/api_keys + email confirm."""
    if not verify_password(current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="invalid password")
    user.status = "deleted"
    user.deleted_at = datetime.now(UTC)
    from sqlalchemy import update

    await revoke_all_sessions(session, user.id)
    await session.execute(
        update(ApiKey)
        .where(ApiKey.user_id == user.id, ApiKey.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await session.execute(
        update(Webhook).where(Webhook.user_id == user.id).values(active=False)
    )
    _record_security_event(
        session, user=user, kind="account_delete", request=request,
    )
    await session.commit()
    return GenericMessage(message="account deleted")


@router.post("/data-export", response_model=GenericMessage)
async def request_data_export(
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    """Tạo DataExportRequest pending. Admin (hoặc cron) sẽ build ZIP."""
    from packages.db.models import DataExportRequest

    # Throttle: chỉ 1 pending request/24h
    recent = (
        await session.scalars(
            select(DataExportRequest)
            .where(DataExportRequest.user_id == user.id)
            .where(DataExportRequest.status.in_(("pending", "ready")))
            .where(
                DataExportRequest.requested_at
                > datetime.now(UTC) - timedelta(hours=24)
            )
        )
    ).first()
    if recent is not None:
        raise HTTPException(
            status_code=429,
            detail="already requested in last 24h",
        )
    req = DataExportRequest(user_id=user.id, status="pending")
    session.add(req)
    _record_security_event(
        session, user=user, kind="data_export_request", request=request,
    )
    await session.commit()
    return GenericMessage(message="queued; admin will fulfill within 7 days")


@router.post("/2fa/recovery-codes/regenerate")
async def regenerate_recovery_codes(
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    current_password: str = Query(..., min_length=1, max_length=128),
) -> dict[str, Any]:
    """Sinh lại 10 recovery code mới (yêu cầu re-auth bằng password)."""
    if not verify_password(current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="invalid password")
    twofa = await session.get(TwoFactor, user.id)
    if twofa is None or twofa.enabled_at is None:
        raise HTTPException(status_code=400, detail="2fa not enabled")
    from packages.security.crypto import FernetCipher

    settings = get_settings()
    if not settings.fernet_keys:
        raise HTTPException(status_code=500, detail="fernet keys not set")
    cipher = FernetCipher.from_keys(settings.fernet_keys)
    codes = [secrets.token_urlsafe(8) for _ in range(10)]
    twofa.recovery_codes_enc = {
        "codes": [cipher.encrypt(c) for c in codes],
    }
    _record_security_event(
        session, user=user, kind="2fa_recovery_regenerate", request=request,
    )
    await session.commit()
    return {"recovery_codes": codes}


@router.get("/security-events")
async def list_security_events(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, Any]]:
    rows = list(
        (
            await session.scalars(
                select(SecurityEvent)
                .where(SecurityEvent.user_id == user.id)
                .order_by(desc(SecurityEvent.created_at))
                .limit(limit)
            )
        ).all()
    )
    return [
        {
            "id": r.id,
            "kind": r.kind,
            "ip": r.ip,
            "user_agent": r.user_agent,
            "detail": r.detail,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# API KEYS — rotate + IP allowlist + mode
# ---------------------------------------------------------------------------


@router.post("/api-keys/{api_key_id}/rotate")
async def rotate_api_key(
    api_key_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Tạo raw key mới cho key id này (giữ scopes/expires/IP allowlist)."""
    record = await session.get(ApiKey, api_key_id)
    if record is None or record.user_id != user.id:
        raise HTTPException(status_code=404, detail="not found")
    if record.revoked_at is not None:
        raise HTTPException(status_code=400, detail="key revoked")
    raw = generate_api_key()
    record.key_hash = hash_api_key(raw, salt=get_settings().api_key_salt)
    _record_security_event(
        session, user=user, kind="api_key_rotate", request=request,
        detail={"api_key_id": api_key_id},
    )
    await session.commit()
    return {"raw_key": raw, "id": record.id}


@router.patch("/api-keys/{api_key_id}", response_model=GenericMessage)
async def update_my_api_key(
    api_key_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    ip_allowlist: list[str] | None = Query(default=None),
    mode: str | None = Query(default=None, pattern="^(live|test)$"),
) -> GenericMessage:
    record = await session.get(ApiKey, api_key_id)
    if record is None or record.user_id != user.id:
        raise HTTPException(status_code=404, detail="not found")
    if ip_allowlist is not None:
        import ipaddress

        for cidr in ip_allowlist:
            try:
                ipaddress.ip_network(cidr, strict=False)
            except ValueError as exc:
                raise HTTPException(
                    status_code=400, detail=f"invalid cidr {cidr}"
                ) from exc
        record.ip_allowlist_json = list(ip_allowlist)
    if mode is not None:
        record.mode = mode
    _record_security_event(
        session, user=user, kind="api_key_update", request=request,
        detail={"id": api_key_id, "mode": record.mode},
    )
    await session.commit()
    return GenericMessage(message="ok")


# ---------------------------------------------------------------------------
# WEBHOOKS — rotate secret
# ---------------------------------------------------------------------------


@router.post("/webhooks/{webhook_id}/rotate-secret", response_model=GenericMessage)
async def rotate_webhook_secret(
    webhook_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    new_secret: str = Query(..., min_length=16, max_length=128),
) -> GenericMessage:
    wh = await session.get(Webhook, webhook_id)
    if wh is None or wh.user_id != user.id:
        raise HTTPException(status_code=404, detail="not found")
    wh.secret_enc = new_secret  # encrypt-at-rest do middleware webhook làm
    _record_security_event(
        session, user=user, kind="webhook_rotate_secret", request=request,
        detail={"webhook_id": webhook_id},
    )
    await session.commit()
    return GenericMessage(message="rotated")


# ---------------------------------------------------------------------------
# USAGE (mirror admin/usage but scoped to user)
# ---------------------------------------------------------------------------


@router.get("/usage/summary")
async def my_usage_summary(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    days: int = Query(default=30, ge=1, le=365),
) -> dict[str, Any]:
    from sqlalchemy import func

    from packages.db.models import ApiUsageDaily

    today = datetime.now(UTC).date()
    since = today - timedelta(days=days - 1)
    totals = (
        await session.execute(
            select(
                func.coalesce(func.sum(ApiUsageDaily.count), 0),
                func.coalesce(func.sum(ApiUsageDaily.error_count), 0),
            )
            .where(ApiUsageDaily.user_id == user.id)
            .where(ApiUsageDaily.day >= since)
        )
    ).first()
    points_rows = (
        await session.execute(
            select(
                ApiUsageDaily.day,
                func.sum(ApiUsageDaily.count),
                func.sum(ApiUsageDaily.error_count),
            )
            .where(ApiUsageDaily.user_id == user.id)
            .where(ApiUsageDaily.day >= since)
            .group_by(ApiUsageDaily.day)
            .order_by(ApiUsageDaily.day)
        )
    ).all()
    bucket = {
        (
            d.isoformat() if hasattr(d, "isoformat") else str(d)
        ): (int(c or 0), int(e or 0))
        for d, c, e in points_rows
    }
    points = []
    for i in range(days):
        d = since + timedelta(days=i)
        cnt, err = bucket.get(d.isoformat(), (0, 0))
        points.append({"day": d.isoformat(), "count": cnt, "error_count": err})
    return {
        "days": days,
        "total_count": int(totals[0] or 0) if totals else 0,
        "total_errors": int(totals[1] or 0) if totals else 0,
        "points": points,
    }


# ---------------------------------------------------------------------------
# BILLING — invoice PDF + cancel sub + auto_renew + prorate preview + tax
# ---------------------------------------------------------------------------


@router.get("/invoices/{invoice_id}/pdf")
async def my_invoice_pdf(
    invoice_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    from fastapi.responses import FileResponse

    from packages.billing import invoice_pdf

    inv = await session.get(Invoice, invoice_id)
    if inv is None or inv.user_id != user.id:
        raise HTTPException(status_code=404, detail="not found")
    path = inv.pdf_path
    if not path:
        # Lazy-gen.
        path = await invoice_pdf.generate(inv, user)
        inv.pdf_path = path
        await session.commit()
    return FileResponse(
        path, media_type="application/pdf", filename=f"invoice-{inv.id}.pdf"
    )


@router.post("/subscription/cancel", response_model=GenericMessage)
async def cancel_my_subscription(
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    sub = (
        await session.scalars(
            select(Subscription)
            .where(Subscription.user_id == user.id)
            .where(Subscription.status == "active")
            .order_by(desc(Subscription.expires_at))
        )
    ).first()
    if sub is None:
        raise HTTPException(status_code=404, detail="no active subscription")
    sub.auto_renew = False
    sub.status = "canceled"
    _record_security_event(
        session, user=user, kind="subscription_cancel", request=request,
        detail={"subscription_id": sub.id},
    )
    await session.commit()
    return GenericMessage(message="canceled")


@router.patch("/subscription", response_model=GenericMessage)
async def update_my_subscription(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    auto_renew: bool = Query(...),
) -> GenericMessage:
    sub = (
        await session.scalars(
            select(Subscription)
            .where(Subscription.user_id == user.id)
            .where(Subscription.status == "active")
            .order_by(desc(Subscription.expires_at))
        )
    ).first()
    if sub is None:
        raise HTTPException(status_code=404, detail="no active subscription")
    sub.auto_renew = auto_renew
    await session.commit()
    return GenericMessage(message="ok")


@router.post("/subscription/preview-change")
async def preview_change_plan(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    plan_code: str = Query(..., min_length=1, max_length=32),
) -> dict[str, Any]:
    """Trả estimated prorate cho việc đổi sang plan_code mới."""
    sub = (
        await session.scalars(
            select(Subscription)
            .where(Subscription.user_id == user.id)
            .where(Subscription.status == "active")
        )
    ).first()
    target_plan = (
        await session.scalars(select(Plan).where(Plan.code == plan_code))
    ).first()
    if target_plan is None:
        raise HTTPException(status_code=404, detail="plan not found")
    if sub is None:
        return {
            "current": None,
            "target_plan": target_plan.code,
            "amount_due_vnd": str(target_plan.price_vnd),
            "credit_vnd": "0",
        }
    current_plan = await session.get(Plan, sub.plan_id)
    now = datetime.now(UTC)
    expires = sub.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    remaining_days = max(0, (expires - now).days)
    credit = (
        Decimal(current_plan.price_vnd) * Decimal(remaining_days)
        / Decimal(max(current_plan.duration_days, 1))
    ) if current_plan else Decimal(0)
    due = max(Decimal(0), Decimal(target_plan.price_vnd) - credit)
    return {
        "current_plan": current_plan.code if current_plan else None,
        "target_plan": target_plan.code,
        "remaining_days": remaining_days,
        "credit_vnd": str(credit.quantize(Decimal("1"))),
        "amount_due_vnd": str(due.quantize(Decimal("1"))),
    }


@router.get("/billing-profile")
async def get_billing_profile(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    profile = await session.get(BillingProfile, user.id)
    return {
        "company_name": profile.company_name if profile else None,
        "tax_code": profile.tax_code if profile else None,
        "address": profile.address if profile else None,
        "billing_email": (
            profile.billing_email if profile and profile.billing_email else user.billing_email
        ),
    }


@router.put("/billing-profile", response_model=GenericMessage)
async def update_billing_profile(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    company_name: str | None = Query(default=None, max_length=255),
    tax_code: str | None = Query(default=None, max_length=32),
    address: str | None = Query(default=None, max_length=1000),
    billing_email: str | None = Query(default=None, max_length=255),
) -> GenericMessage:
    profile = await session.get(BillingProfile, user.id)
    if profile is None:
        profile = BillingProfile(user_id=user.id)
        session.add(profile)
    profile.company_name = company_name
    profile.tax_code = tax_code
    profile.address = address
    profile.billing_email = billing_email
    if billing_email:
        user.billing_email = billing_email
    await session.commit()
    return GenericMessage(message="ok")


# ---------------------------------------------------------------------------
# WALLET — export CSV + withdraw
# ---------------------------------------------------------------------------


@router.get("/wallet/transactions/export.csv")
async def export_my_wallet_csv(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    type_: str | None = Query(default=None, alias="type"),
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
) -> Any:
    stmt = select(WalletTransaction).where(WalletTransaction.user_id == user.id)
    if type_:
        stmt = stmt.where(WalletTransaction.type == type_)
    if date_from:
        stmt = stmt.where(WalletTransaction.created_at >= date_from)
    if date_to:
        stmt = stmt.where(WalletTransaction.created_at <= date_to)

    async def _gen() -> AsyncIterator[bytes]:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "id",
                "type",
                "amount_vnd",
                "balance_after",
                "ref_kind",
                "ref_id",
                "note",
                "created_at",
            ]
        )
        yield buf.getvalue().encode("utf-8")
        buf.seek(0)
        buf.truncate(0)
        rows = list(
            (
                await session.scalars(
                    stmt.order_by(desc(WalletTransaction.created_at))
                )
            ).all()
        )
        for r in rows:
            writer.writerow(
                [
                    r.id,
                    r.type,
                    int(r.amount_vnd),
                    int(r.balance_after),
                    r.ref_kind or "",
                    r.ref_id or "",
                    r.note or "",
                    r.created_at.isoformat(),
                ]
            )
            yield buf.getvalue().encode("utf-8")
            buf.seek(0)
            buf.truncate(0)

    return StreamingResponse(
        _gen(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=wallet.csv"},
    )


@router.post("/wallet/withdraw", response_model=GenericMessage)
async def request_withdraw(
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    amount_vnd: int = Query(..., ge=10_000),
    bank_account_id: str = Query(..., min_length=1),
    note: str | None = Query(default=None, max_length=500),
) -> GenericMessage:
    if Decimal(amount_vnd) > Decimal(user.balance_vnd):
        raise HTTPException(status_code=400, detail="insufficient balance")
    bank = await session.get(BankAccount, bank_account_id)
    if bank is None or bank.user_id != user.id:
        raise HTTPException(status_code=404, detail="bank account not found")
    if bank.verified_at is None:
        raise HTTPException(status_code=400, detail="bank account chưa verify")
    req = WithdrawalRequest(
        user_id=user.id,
        bank_account_id=bank_account_id,
        amount_vnd=Decimal(amount_vnd),
        note=note,
        status="pending",
    )
    session.add(req)
    _record_security_event(
        session, user=user, kind="withdraw_request", request=request,
        detail={"amount_vnd": amount_vnd, "bank_account_id": bank_account_id},
    )
    await session.commit()
    return GenericMessage(message="queued; admin will review")


@router.get("/withdrawals")
async def list_my_withdrawals(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, Any]]:
    rows = list(
        (
            await session.scalars(
                select(WithdrawalRequest)
                .where(WithdrawalRequest.user_id == user.id)
                .order_by(desc(WithdrawalRequest.requested_at))
                .limit(limit)
            )
        ).all()
    )
    return [
        {
            "id": r.id,
            "amount_vnd": str(r.amount_vnd),
            "bank_account_id": r.bank_account_id,
            "status": r.status,
            "note": r.note,
            "admin_note": r.admin_note,
            "requested_at": r.requested_at.isoformat(),
            "decided_at": r.decided_at.isoformat() if r.decided_at else None,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# BANK ACCOUNT — primary selection
# ---------------------------------------------------------------------------


@router.post("/bank-accounts/{bank_id}:set-primary", response_model=GenericMessage)
async def set_primary_bank(
    bank_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    target = await session.get(BankAccount, bank_id)
    if target is None or target.user_id != user.id:
        raise HTTPException(status_code=404, detail="not found")
    from sqlalchemy import update

    await session.execute(
        update(BankAccount)
        .where(BankAccount.user_id == user.id)
        .values(is_primary=False)
    )
    target.is_primary = True
    await session.commit()
    return GenericMessage(message="primary set")


# ---------------------------------------------------------------------------
# NOTIFICATIONS — snooze/mute
# ---------------------------------------------------------------------------


@router.post("/notification-preferences/{kind}/{channel}:mute", response_model=GenericMessage)
async def mute_notification(
    kind: str,
    channel: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    until: datetime | None = Query(default=None),
    days: int | None = Query(default=None, ge=1, le=365),
) -> GenericMessage:
    from packages.db.models import NotificationPreference

    pref = (
        await session.scalars(
            select(NotificationPreference)
            .where(NotificationPreference.user_id == user.id)
            .where(NotificationPreference.kind == kind)
            .where(NotificationPreference.channel == channel)
        )
    ).first()
    if pref is None:
        pref = NotificationPreference(
            user_id=user.id, kind=kind, channel=channel, enabled=True
        )
        session.add(pref)
    if until is None and days is not None:
        until = datetime.now(UTC) + timedelta(days=days)
    pref.muted_until = until
    await session.commit()
    return GenericMessage(message="muted")


# ---------------------------------------------------------------------------
# SUPPORT TICKETS
# ---------------------------------------------------------------------------


@router.get("/tickets")
async def list_tickets(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    rows = list(
        (
            await session.scalars(
                select(SupportTicket)
                .where(SupportTicket.user_id == user.id)
                .order_by(desc(SupportTicket.updated_at))
            )
        ).all()
    )
    return [
        {
            "id": t.id,
            "subject": t.subject,
            "status": t.status,
            "created_at": t.created_at.isoformat(),
            "updated_at": t.updated_at.isoformat(),
        }
        for t in rows
    ]


@router.post("/tickets", response_model=dict)
async def create_ticket(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    subject: str = Query(..., min_length=1, max_length=255),
    body: str = Query(..., min_length=1, max_length=10_000),
) -> dict[str, Any]:
    ticket = SupportTicket(user_id=user.id, subject=subject)
    session.add(ticket)
    await session.flush()
    session.add(
        TicketMessage(
            ticket_id=ticket.id, author_id=user.id, is_admin=False, body=body
        )
    )
    await session.commit()
    return {"id": ticket.id, "status": ticket.status}


@router.get("/tickets/{ticket_id}")
async def get_ticket(
    ticket_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    t = await session.get(SupportTicket, ticket_id)
    if t is None or t.user_id != user.id:
        raise HTTPException(status_code=404, detail="not found")
    msgs = list(
        (
            await session.scalars(
                select(TicketMessage)
                .where(TicketMessage.ticket_id == ticket_id)
                .order_by(TicketMessage.created_at)
            )
        ).all()
    )
    return {
        "id": t.id,
        "subject": t.subject,
        "status": t.status,
        "messages": [
            {
                "id": m.id,
                "author_id": m.author_id,
                "is_admin": m.is_admin,
                "body": m.body,
                "created_at": m.created_at.isoformat(),
            }
            for m in msgs
        ],
    }


@router.post("/tickets/{ticket_id}/messages", response_model=GenericMessage)
async def reply_ticket(
    ticket_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    body: str = Query(..., min_length=1, max_length=10_000),
) -> GenericMessage:
    t = await session.get(SupportTicket, ticket_id)
    if t is None or t.user_id != user.id:
        raise HTTPException(status_code=404, detail="not found")
    if t.status == "closed":
        raise HTTPException(status_code=400, detail="ticket closed")
    session.add(
        TicketMessage(
            ticket_id=ticket_id, author_id=user.id, is_admin=False, body=body
        )
    )
    t.status = "open"
    t.updated_at = datetime.now(UTC)
    await session.commit()
    return GenericMessage(message="sent")


# Suppress unused
_ = (status, generate_token, consume_email_token, hash_password)


__all__ = ["router"]
