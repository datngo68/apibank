"""Admin console API — /api/v1/admin/*.

Phục vụ SPA admin /app/admin/*. Tất cả endpoint require role admin/owner qua
`current_admin_user`. Audit mọi thao tác ghi/đổi state.
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.billing import wallet
from packages.config import runtime as config_runtime
from packages.config.settings import get_settings
from packages.db.models import (
    ApiKey,
    ApiUsageDaily,
    AuditLog,
    BankAccount,
    Coupon,
    CouponRedemption,
    EmailToken,
    Invoice,
    Order,
    Plan,
    Subscription,
    Transaction,
    TwoFactor,
    User,
    WalletTransaction,
    utcnow,
)
from packages.db.models import (
    Session as SessionModel,
)
from packages.db.session import get_session
from packages.notifications import email as email_pkg
from packages.notifications import telegram as tg
from packages.schemas.admin import (
    AdminApiKeyCreate,
    AdminApiKeyCreated,
    AdminApiKeyListResponse,
    AdminApiKeyRead,
    AdminAuditItem,
    AdminAuditResponse,
    AdminBankAccountRead,
    AdminCouponCreate,
    AdminCouponRead,
    AdminCouponRedemptionRead,
    AdminCouponUpdate,
    AdminInvoiceListResponse,
    AdminInvoiceRead,
    AdminPlanCreate,
    AdminPlanRead,
    AdminPlanUpdate,
    AdminRevenueByCouponRow,
    AdminRevenueByPlanRow,
    AdminRevenuePoint,
    AdminRevenueSummary,
    AdminRevenueTimeseries,
    AdminStats,
    AdminSystemBankSet,
    AdminUsageApiKeyBreakdown,
    AdminUsageDailyPoint,
    AdminUsageEndpointRow,
    AdminUsageSummary,
    AdminUsageTimeseries,
    AdminUsageUserRow,
    AdminUserDetail,
    AdminUserListItem,
    AdminUserListResponse,
    AdminUserUpdate,
    AdminUserUsageDetail,
    GoogleConfigRead,
    GoogleConfigUpdate,
    SmtpConfigRead,
    SmtpConfigUpdate,
    SmtpTestRequest,
    SmtpTestResponse,
    TelegramConfigRead,
    TelegramConfigUpdate,
    TelegramLinkChatResponse,
    TelegramRegisterWebhookRequest,
    TelegramRegisterWebhookResponse,
    WalletOpRequest,
    WalletOpResponse,
)
from packages.schemas.auth import GenericMessage
from packages.security import oauth_google
from packages.security.api_keys import generate_api_key, hash_api_key
from packages.security.audit import record_audit
from packages.security.email_tokens import KIND_RESET, issue_email_token
from packages.security.tokens import generate_token, hash_token
from packages.security.user_auth import current_admin_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/admin", tags=["admin-console"])


# ---------------------------------------------------------------------------
# USERS
# ---------------------------------------------------------------------------


@router.get("/users", response_model=AdminUserListResponse)
async def list_users(
    q: str | None = None,
    role: str | None = None,
    user_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> AdminUserListResponse:
    stmt = select(User)
    count_stmt = select(func.count()).select_from(User)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(User.email.ilike(like), User.full_name.ilike(like)))
        count_stmt = count_stmt.where(
            or_(User.email.ilike(like), User.full_name.ilike(like))
        )
    if role:
        stmt = stmt.where(User.role == role)
        count_stmt = count_stmt.where(User.role == role)
    if user_status:
        stmt = stmt.where(User.status == user_status)
        count_stmt = count_stmt.where(User.status == user_status)

    total = int((await session.execute(count_stmt)).scalar_one() or 0)
    stmt = stmt.order_by(desc(User.created_at)).limit(limit).offset(offset)
    rows = list((await session.scalars(stmt)).all())
    return AdminUserListResponse(
        items=[AdminUserListItem.model_validate(r, from_attributes=True) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/users/{user_id}", response_model=AdminUserDetail)
async def get_user_detail(
    user_id: str,
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> AdminUserDetail:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")

    twofa = await session.get(TwoFactor, user.id)
    has_2fa = twofa is not None and twofa.enabled_at is not None

    bank_count = int(
        (
            await session.execute(
                select(func.count())
                .select_from(BankAccount)
                .where(BankAccount.user_id == user.id)
                .where(BankAccount.status != "deleted")
            )
        ).scalar_one()
        or 0
    )
    sess_count = int(
        (
            await session.execute(
                select(func.count())
                .select_from(SessionModel)
                .where(SessionModel.user_id == user.id)
                .where(SessionModel.revoked_at.is_(None))
            )
        ).scalar_one()
        or 0
    )

    api_keys_count = int(
        (
            await session.execute(
                select(func.count())
                .select_from(ApiKey)
                .where(ApiKey.user_id == user.id)
                .where(ApiKey.revoked_at.is_(None))
            )
        ).scalar_one()
        or 0
    )
    recent_keys_rows = list(
        (
            await session.scalars(
                select(ApiKey)
                .where(ApiKey.user_id == user.id)
                .order_by(desc(ApiKey.created_at))
                .limit(5)
            )
        ).all()
    )
    recent_api_keys = [
        {
            "id": r.id,
            "name": r.name,
            "scopes": list(r.scopes or []),
            "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None,
            "expires_at": r.expires_at.isoformat() if r.expires_at else None,
            "revoked_at": r.revoked_at.isoformat() if r.revoked_at else None,
            "created_at": r.created_at.isoformat(),
        }
        for r in recent_keys_rows
    ]

    sub_row = (
        await session.scalars(
            select(Subscription)
            .where(Subscription.user_id == user.id)
            .where(Subscription.status == "active")
            .order_by(desc(Subscription.expires_at))
        )
    ).first()
    sub_payload: dict[str, Any] | None = None
    if sub_row is not None:
        plan = await session.get(Plan, sub_row.plan_id)
        sub_payload = {
            "id": sub_row.id,
            "plan_code": plan.code if plan else None,
            "started_at": sub_row.started_at.isoformat(),
            "expires_at": sub_row.expires_at.isoformat(),
            "status": sub_row.status,
        }

    tx_rows = list(
        (
            await session.scalars(
                select(WalletTransaction)
                .where(WalletTransaction.user_id == user.id)
                .order_by(desc(WalletTransaction.created_at))
                .limit(10)
            )
        ).all()
    )
    recent_tx = [
        {
            "id": r.id,
            "type": r.type,
            "amount_vnd": str(r.amount_vnd),
            "balance_after": str(r.balance_after),
            "note": r.note,
            "created_at": r.created_at.isoformat(),
        }
        for r in tx_rows
    ]

    return AdminUserDetail(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        status=user.status,
        balance_vnd=Decimal(user.balance_vnd),
        locale=user.locale,
        has_2fa=has_2fa,
        email_verified_at=user.email_verified_at,
        telegram_chat_id=user.telegram_chat_id,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        bank_accounts_count=bank_count,
        sessions_count=sess_count,
        api_keys_count=api_keys_count,
        subscription=sub_payload,
        recent_wallet_tx=recent_tx,
        recent_api_keys=recent_api_keys,
    )


@router.patch("/users/{user_id}", response_model=AdminUserListItem)
async def update_user(
    user_id: str,
    payload: AdminUserUpdate,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> AdminUserListItem:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")

    before = {"role": user.role, "status": user.status, "full_name": user.full_name}
    if payload.role is not None:
        user.role = payload.role
    if payload.status is not None:
        user.status = payload.status
    if payload.full_name is not None:
        user.full_name = payload.full_name.strip() or None
    if payload.admin_role_extra is not None:
        user.admin_role_extra = payload.admin_role_extra

    await record_audit(
        session,
        actor=actor.id,
        action="admin.user.update",
        target_type="user",
        target_id=user.id,
        ip=request.client.host if request.client else None,
        before=before,
        after={
            "role": user.role,
            "status": user.status,
            "full_name": user.full_name,
            "admin_role_extra": user.admin_role_extra,
        },
    )
    await session.commit()
    return AdminUserListItem.model_validate(user, from_attributes=True)


async def _wallet_op(
    *,
    session: AsyncSession,
    request: Request,
    actor: User,
    target_user: User,
    op: str,
    payload: WalletOpRequest,
) -> WalletOpResponse:
    amount = Decimal(payload.amount_vnd)
    note = payload.note.strip() or None
    idem_key = f"admin-{op}:{target_user.id}:{actor.id}:{secrets.token_hex(8)}"

    if op == "credit":
        if amount <= 0:
            raise HTTPException(status_code=400, detail="amount must be positive")
        tx = await wallet.credit(
            session,
            user_id=target_user.id,
            amount_vnd=amount,
            idempotency_key=idem_key,
            ref_kind="admin",
            ref_id=actor.id,
            note=note,
            created_by=f"admin:{actor.email}",
        )
    elif op == "refund":
        if amount <= 0:
            raise HTTPException(status_code=400, detail="amount must be positive")
        tx = await wallet.refund(
            session,
            user_id=target_user.id,
            amount_vnd=amount,
            idempotency_key=idem_key,
            ref_kind="admin",
            ref_id=payload.ref_id or actor.id,
            note=note,
            created_by=f"admin:{actor.email}",
        )
    elif op == "adjust":
        if amount == 0:
            raise HTTPException(status_code=400, detail="amount must be non-zero")
        tx = await wallet.adjust(
            session,
            user_id=target_user.id,
            amount_vnd=amount,
            idempotency_key=idem_key,
            note=note,
            created_by=f"admin:{actor.email}",
        )
    else:
        raise HTTPException(status_code=400, detail=f"unknown op: {op}")

    await record_audit(
        session,
        actor=actor.id,
        action=f"admin.wallet.{op}",
        target_type="user",
        target_id=target_user.id,
        ip=request.client.host if request.client else None,
        after={
            "amount_vnd": int(amount),
            "balance_after": int(tx.balance_after),
            "tx_id": tx.id,
            "note": note,
        },
    )
    await session.commit()
    return WalletOpResponse(
        tx_id=tx.id,
        balance_after=Decimal(tx.balance_after),
        amount_vnd=Decimal(tx.amount_vnd),
    )


@router.post("/users/{user_id}/wallet/credit", response_model=WalletOpResponse)
async def admin_credit(
    user_id: str,
    payload: WalletOpRequest,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> WalletOpResponse:
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    return await _wallet_op(
        session=session, request=request, actor=actor, target_user=target,
        op="credit", payload=payload,
    )


@router.post("/users/{user_id}/wallet/refund", response_model=WalletOpResponse)
async def admin_refund(
    user_id: str,
    payload: WalletOpRequest,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> WalletOpResponse:
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    return await _wallet_op(
        session=session, request=request, actor=actor, target_user=target,
        op="refund", payload=payload,
    )


@router.post("/users/{user_id}/wallet/adjust", response_model=WalletOpResponse)
async def admin_adjust(
    user_id: str,
    payload: WalletOpRequest,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> WalletOpResponse:
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    return await _wallet_op(
        session=session, request=request, actor=actor, target_user=target,
        op="adjust", payload=payload,
    )


@router.post("/users/{user_id}/reset-password", response_model=GenericMessage)
async def admin_reset_password(
    user_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    raw, _ = await issue_email_token(session, target, KIND_RESET)
    await record_audit(
        session,
        actor=actor.id,
        action="admin.user.reset_password",
        target_type="user",
        target_id=target.id,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    body = (
        f"Admin {actor.email} đã yêu cầu đặt lại mật khẩu cho bạn.\n"
        f"Token đặt lại (link): /reset?token={raw}\n"
        f"Token hết hạn sau 1 giờ."
    )
    await email_pkg.send_email(
        to=target.email, subject="APIBank · Đặt lại mật khẩu", body=body, session=session
    )
    return GenericMessage(message="reset email sent")


@router.post("/users/{user_id}/disable-2fa", response_model=GenericMessage)
async def admin_disable_2fa(
    user_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    twofa = await session.get(TwoFactor, target.id)
    if twofa is not None:
        await session.delete(twofa)
    await record_audit(
        session,
        actor=actor.id,
        action="admin.user.disable_2fa",
        target_type="user",
        target_id=target.id,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return GenericMessage(message="2fa disabled")


# ---------------------------------------------------------------------------
# PLANS CRUD
# ---------------------------------------------------------------------------


@router.get("/plans", response_model=list[AdminPlanRead])
async def admin_list_plans(
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> list[AdminPlanRead]:
    rows = list(
        (await session.scalars(select(Plan).order_by(Plan.sort_order, Plan.code))).all()
    )
    return [AdminPlanRead.model_validate(r, from_attributes=True) for r in rows]


@router.post("/plans", response_model=AdminPlanRead, status_code=status.HTTP_201_CREATED)
async def admin_create_plan(
    payload: AdminPlanCreate,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> AdminPlanRead:
    existing = (
        await session.scalars(select(Plan).where(Plan.code == payload.code))
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="plan code already exists")
    plan = Plan(
        code=payload.code,
        name=payload.name,
        description=payload.description,
        price_vnd=Decimal(payload.price_vnd),
        duration_days=payload.duration_days,
        daily_quota=payload.daily_quota,
        monthly_quota=payload.monthly_quota,
        features_json=payload.features_json,
        sort_order=payload.sort_order,
        active=payload.active,
    )
    session.add(plan)
    await session.flush()
    await record_audit(
        session,
        actor=actor.id,
        action="admin.plan.create",
        target_type="plan",
        target_id=plan.id,
        ip=request.client.host if request.client else None,
        after={"code": plan.code, "price_vnd": str(plan.price_vnd)},
    )
    await session.commit()
    return AdminPlanRead.model_validate(plan, from_attributes=True)


@router.patch("/plans/{plan_id}", response_model=AdminPlanRead)
async def admin_update_plan(
    plan_id: str,
    payload: AdminPlanUpdate,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> AdminPlanRead:
    plan = await session.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="plan not found")
    data = payload.model_dump(exclude_unset=True)
    for field, val in data.items():
        if field == "price_vnd" and val is not None:
            plan.price_vnd = Decimal(val)
        else:
            setattr(plan, field, val)
    await record_audit(
        session,
        actor=actor.id,
        action="admin.plan.update",
        target_type="plan",
        target_id=plan.id,
        ip=request.client.host if request.client else None,
        after=data,
    )
    await session.commit()
    return AdminPlanRead.model_validate(plan, from_attributes=True)


@router.delete("/plans/{plan_id}", response_model=GenericMessage)
async def admin_delete_plan(
    plan_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    plan = await session.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="plan not found")
    plan.active = False
    await record_audit(
        session,
        actor=actor.id,
        action="admin.plan.delete",
        target_type="plan",
        target_id=plan.id,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return GenericMessage(message="deactivated")


@router.post("/plans/{plan_id}:clone", response_model=AdminPlanRead)
async def admin_clone_plan(
    plan_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
    new_code: str = Query(..., min_length=1, max_length=32, pattern="^[a-z0-9-]+$"),
) -> AdminPlanRead:
    src = await session.get(Plan, plan_id)
    if src is None:
        raise HTTPException(status_code=404, detail="plan not found")
    existing = (
        await session.scalars(select(Plan).where(Plan.code == new_code))
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="code already exists")
    clone = Plan(
        code=new_code,
        name=f"{src.name} (copy)",
        description=src.description,
        price_vnd=src.price_vnd,
        duration_days=src.duration_days,
        daily_quota=src.daily_quota,
        monthly_quota=src.monthly_quota,
        features_json=dict(src.features_json or {}),
        sort_order=src.sort_order,
        active=False,  # an toàn: clone tắt mặc định
    )
    session.add(clone)
    await session.flush()
    await record_audit(
        session,
        actor=actor.id,
        action="admin.plan.clone",
        target_type="plan",
        target_id=clone.id,
        ip=request.client.host if request.client else None,
        after={"source": plan_id, "new_code": new_code},
    )
    await session.commit()
    return AdminPlanRead.model_validate(clone, from_attributes=True)


@router.post("/plans/{plan_id}:archive", response_model=GenericMessage)
async def admin_archive_plan(
    plan_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    plan = await session.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="not found")
    plan.archived_at = datetime.now(UTC)
    plan.active = False
    await record_audit(
        session,
        actor=actor.id,
        action="admin.plan.archive",
        target_type="plan",
        target_id=plan.id,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return GenericMessage(message="archived")


# ---------------------------------------------------------------------------
# COUPONS
# ---------------------------------------------------------------------------


def _coupon_to_read(coupon: Coupon) -> AdminCouponRead:
    return AdminCouponRead.model_validate(coupon, from_attributes=True)


@router.get("/coupons", response_model=list[AdminCouponRead])
async def admin_list_coupons(
    active_only: bool = Query(default=False),
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> list[AdminCouponRead]:
    stmt = select(Coupon).order_by(desc(Coupon.created_at))
    if active_only:
        stmt = stmt.where(Coupon.active.is_(True))
    rows = list((await session.scalars(stmt)).all())
    return [_coupon_to_read(r) for r in rows]


@router.post(
    "/coupons", response_model=AdminCouponRead, status_code=status.HTTP_201_CREATED
)
async def admin_create_coupon(
    payload: AdminCouponCreate,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> AdminCouponRead:
    code = payload.code.strip().upper()
    existing = (
        await session.scalars(select(Coupon).where(Coupon.code == code))
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="coupon code already exists")
    coupon = Coupon(
        code=code,
        description=payload.description,
        discount_type=payload.discount_type,
        percent_off=payload.percent_off,
        amount_off_vnd=(
            Decimal(payload.amount_off_vnd)
            if payload.amount_off_vnd is not None
            else None
        ),
        max_discount_vnd=(
            Decimal(payload.max_discount_vnd)
            if payload.max_discount_vnd is not None
            else None
        ),
        min_amount_vnd=(
            Decimal(payload.min_amount_vnd)
            if payload.min_amount_vnd is not None
            else None
        ),
        max_redemptions=payload.max_redemptions,
        max_per_user=payload.max_per_user,
        valid_from=payload.valid_from,
        valid_until=payload.valid_until,
        plan_codes_json=list(payload.plan_codes),
        active=payload.active,
        created_by=actor.id,
    )
    session.add(coupon)
    await session.flush()
    await record_audit(
        session,
        actor=actor.id,
        action="admin.coupon.create",
        target_type="coupon",
        target_id=coupon.id,
        ip=request.client.host if request.client else None,
        after={
            "code": coupon.code,
            "discount_type": coupon.discount_type,
            "percent_off": coupon.percent_off,
            "amount_off_vnd": (
                str(coupon.amount_off_vnd)
                if coupon.amount_off_vnd is not None
                else None
            ),
        },
    )
    await session.commit()
    return _coupon_to_read(coupon)


@router.patch("/coupons/{coupon_id}", response_model=AdminCouponRead)
async def admin_update_coupon(
    coupon_id: str,
    payload: AdminCouponUpdate,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> AdminCouponRead:
    coupon = await session.get(Coupon, coupon_id)
    if coupon is None:
        raise HTTPException(status_code=404, detail="coupon not found")
    data = payload.model_dump(exclude_unset=True)
    if "plan_codes" in data:
        coupon.plan_codes_json = list(data.pop("plan_codes") or [])
    for field, val in data.items():
        setattr(coupon, field, val)
    if (
        coupon.valid_from is not None
        and coupon.valid_until is not None
        and coupon.valid_from >= coupon.valid_until
    ):
        raise HTTPException(status_code=422, detail="valid_until phải sau valid_from")
    await record_audit(
        session,
        actor=actor.id,
        action="admin.coupon.update",
        target_type="coupon",
        target_id=coupon.id,
        ip=request.client.host if request.client else None,
        after=data,
    )
    await session.commit()
    return _coupon_to_read(coupon)


@router.delete("/coupons/{coupon_id}", response_model=GenericMessage)
async def admin_delete_coupon(
    coupon_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    """Xoá vĩnh viễn nếu chưa có redemption, ngược lại trả 409.

    Admin nên `active=false` thay vì xoá khi đã có người dùng để giữ audit.
    """
    coupon = await session.get(Coupon, coupon_id)
    if coupon is None:
        raise HTTPException(status_code=404, detail="coupon not found")
    if coupon.redeemed_count > 0:
        raise HTTPException(
            status_code=409,
            detail="coupon đã có người dùng — đặt active=false thay vì xoá",
        )
    await session.delete(coupon)
    await record_audit(
        session,
        actor=actor.id,
        action="admin.coupon.delete",
        target_type="coupon",
        target_id=coupon_id,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return GenericMessage(message="deleted")


@router.get(
    "/coupons/{coupon_id}/redemptions",
    response_model=list[AdminCouponRedemptionRead],
)
async def admin_list_coupon_redemptions(
    coupon_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> list[AdminCouponRedemptionRead]:
    coupon = await session.get(Coupon, coupon_id)
    if coupon is None:
        raise HTTPException(status_code=404, detail="coupon not found")
    rows = list(
        (
            await session.scalars(
                select(CouponRedemption)
                .where(CouponRedemption.coupon_id == coupon_id)
                .order_by(desc(CouponRedemption.created_at))
                .limit(limit)
            )
        ).all()
    )
    return [
        AdminCouponRedemptionRead.model_validate(r, from_attributes=True) for r in rows
    ]


@router.get("/coupons/{coupon_id}/by-user")
async def admin_coupon_redemptions_by_user(
    coupon_id: str,
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """Aggregate redemption coupon theo user (count + total discount)."""
    coupon = await session.get(Coupon, coupon_id)
    if coupon is None:
        raise HTTPException(status_code=404, detail="coupon not found")
    rows = (
        await session.execute(
            select(
                CouponRedemption.user_id,
                User.email,
                func.count(CouponRedemption.id),
                func.coalesce(func.sum(CouponRedemption.discount_vnd), 0),
            )
            .outerjoin(User, User.id == CouponRedemption.user_id)
            .where(CouponRedemption.coupon_id == coupon_id)
            .group_by(CouponRedemption.user_id, User.email)
            .order_by(desc(func.sum(CouponRedemption.discount_vnd)))
        )
    ).all()
    return [
        {
            "user_id": r[0],
            "user_email": r[1],
            "redemptions": int(r[2] or 0),
            "discount_vnd": str(r[3] or 0),
        }
        for r in rows
    ]


@router.post("/coupons/{coupon_id}:clone", response_model=AdminCouponRead)
async def admin_clone_coupon(
    coupon_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
    new_code: str = Query(..., min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
) -> AdminCouponRead:
    src = await session.get(Coupon, coupon_id)
    if src is None:
        raise HTTPException(status_code=404, detail="coupon not found")
    new_code_upper = new_code.upper()
    existing = (
        await session.scalars(select(Coupon).where(Coupon.code == new_code_upper))
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="code already exists")
    clone = Coupon(
        code=new_code_upper,
        description=src.description,
        discount_type=src.discount_type,
        percent_off=src.percent_off,
        amount_off_vnd=src.amount_off_vnd,
        max_discount_vnd=src.max_discount_vnd,
        min_amount_vnd=src.min_amount_vnd,
        max_redemptions=src.max_redemptions,
        max_per_user=src.max_per_user,
        valid_from=src.valid_from,
        valid_until=src.valid_until,
        plan_codes_json=list(src.plan_codes_json or []),
        active=False,
        created_by=actor.id,
    )
    session.add(clone)
    await session.flush()
    await record_audit(
        session,
        actor=actor.id,
        action="admin.coupon.clone",
        target_type="coupon",
        target_id=clone.id,
        ip=request.client.host if request.client else None,
        after={"source": coupon_id, "new_code": new_code_upper},
    )
    await session.commit()
    return _coupon_to_read(clone)


@router.post("/coupons/import")
async def admin_import_coupons(
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
    items: list[AdminCouponCreate] | None = None,
) -> dict[str, Any]:
    """Bulk create coupon từ payload JSON.

    Body là list ``AdminCouponCreate``. Skip những coupon trùng code.
    """
    if not items:
        return {"created": 0, "skipped": 0, "errors": []}
    created = 0
    skipped = 0
    errors: list[dict[str, Any]] = []
    for payload in items:
        code = payload.code.strip().upper()
        existing = (
            await session.scalars(select(Coupon).where(Coupon.code == code))
        ).first()
        if existing is not None:
            skipped += 1
            continue
        try:
            coupon = Coupon(
                code=code,
                description=payload.description,
                discount_type=payload.discount_type,
                percent_off=payload.percent_off,
                amount_off_vnd=(
                    Decimal(payload.amount_off_vnd)
                    if payload.amount_off_vnd is not None
                    else None
                ),
                max_discount_vnd=(
                    Decimal(payload.max_discount_vnd)
                    if payload.max_discount_vnd is not None
                    else None
                ),
                min_amount_vnd=(
                    Decimal(payload.min_amount_vnd)
                    if payload.min_amount_vnd is not None
                    else None
                ),
                max_redemptions=payload.max_redemptions,
                max_per_user=payload.max_per_user,
                valid_from=payload.valid_from,
                valid_until=payload.valid_until,
                plan_codes_json=list(payload.plan_codes),
                active=payload.active,
                created_by=actor.id,
            )
            session.add(coupon)
            created += 1
        except Exception as exc:  # noqa: BLE001
            errors.append({"code": code, "error": str(exc)})

    await record_audit(
        session,
        actor=actor.id,
        action="admin.coupon.import",
        target_type="coupon",
        target_id="*",
        ip=request.client.host if request.client else None,
        after={"created": created, "skipped": skipped, "errors": len(errors)},
    )
    await session.commit()
    return {"created": created, "skipped": skipped, "errors": errors}


# ---------------------------------------------------------------------------
# BANK ACCOUNTS / SYSTEM BANK
# ---------------------------------------------------------------------------


@router.get("/bank-accounts", response_model=list[AdminBankAccountRead])
async def admin_list_bank_accounts(
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> list[AdminBankAccountRead]:
    stmt = (
        select(BankAccount, User.email)
        .outerjoin(User, BankAccount.user_id == User.id)
        .where(BankAccount.status != "deleted")
        .order_by(desc(BankAccount.is_system_account), desc(BankAccount.created_at))
    )
    rows = (await session.execute(stmt)).all()
    out: list[AdminBankAccountRead] = []
    for ba, email in rows:
        out.append(
            AdminBankAccountRead(
                id=ba.id,
                user_id=ba.user_id,
                user_email=email,
                bank_code=ba.bank_code,
                account_no=ba.account_no,
                account_holder=ba.account_holder,
                status=ba.status,
                polling_enabled=ba.polling_enabled,
                polling_status=ba.polling_status,
                is_system_account=ba.is_system_account,
                last_poll_at=ba.last_poll_at,
                last_error=ba.last_error,
                created_at=ba.created_at,
            )
        )
    return out


@router.get("/system-bank", response_model=AdminBankAccountRead | None)
async def admin_get_system_bank(
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> AdminBankAccountRead | None:
    row = (
        await session.scalars(
            select(BankAccount).where(BankAccount.is_system_account.is_(True))
        )
    ).first()
    if row is None:
        return None
    user_email = None
    if row.user_id:
        user = await session.get(User, row.user_id)
        user_email = user.email if user else None
    return AdminBankAccountRead(
        id=row.id,
        user_id=row.user_id,
        user_email=user_email,
        bank_code=row.bank_code,
        account_no=row.account_no,
        account_holder=row.account_holder,
        status=row.status,
        polling_enabled=row.polling_enabled,
        polling_status=row.polling_status,
        is_system_account=True,
        last_poll_at=row.last_poll_at,
        last_error=row.last_error,
        created_at=row.created_at,
    )


@router.post("/system-bank", response_model=GenericMessage)
async def admin_set_system_bank(
    payload: AdminSystemBankSet,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    target = await session.get(BankAccount, payload.bank_account_id)
    if target is None:
        raise HTTPException(status_code=404, detail="bank account not found")
    others = list(
        (
            await session.scalars(
                select(BankAccount).where(BankAccount.is_system_account.is_(True))
            )
        ).all()
    )
    for ba in others:
        ba.is_system_account = False
    target.is_system_account = True
    await record_audit(
        session,
        actor=actor.id,
        action="admin.system_bank.set",
        target_type="bank_account",
        target_id=target.id,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return GenericMessage(message="ok")


@router.delete("/system-bank", response_model=GenericMessage)
async def admin_unset_system_bank(
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    rows = list(
        (
            await session.scalars(
                select(BankAccount).where(BankAccount.is_system_account.is_(True))
            )
        ).all()
    )
    for ba in rows:
        ba.is_system_account = False
    await record_audit(
        session,
        actor=actor.id,
        action="admin.system_bank.unset",
        target_type="bank_account",
        target_id="*",
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return GenericMessage(message="ok")


# ---------------------------------------------------------------------------
# BANK ACCOUNT OPS (re-poll, toggle, rotate creds, reset cursor, soft-delete)
# ---------------------------------------------------------------------------


@router.post("/bank-accounts/{bank_id}:poll", response_model=GenericMessage)
async def admin_force_poll(
    bank_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    """Force trigger 1 chu kỳ poll ngay (qua poll_kick)."""
    from packages.banks import poll_kick

    bank = await session.get(BankAccount, bank_id)
    if bank is None:
        raise HTTPException(status_code=404, detail="bank account not found")
    # Local kick (nếu worker cùng process); Redis kick cho cluster.
    poll_kick.set_local(bank_id)
    try:
        await poll_kick.kick(bank_id)
    except Exception:  # noqa: BLE001
        logger.exception("admin_force_poll_kick_failed", extra={"bank_id": bank_id})
    await record_audit(
        session,
        actor=actor.id,
        action="admin.bank.force_poll",
        target_type="bank_account",
        target_id=bank_id,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return GenericMessage(message="kicked")


@router.patch("/bank-accounts/{bank_id}", response_model=GenericMessage)
async def admin_update_bank_account(
    bank_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
    polling_enabled: bool | None = None,
) -> GenericMessage:
    bank = await session.get(BankAccount, bank_id)
    if bank is None:
        raise HTTPException(status_code=404, detail="bank account not found")
    before = {"polling_enabled": bank.polling_enabled}
    if polling_enabled is not None:
        bank.polling_enabled = polling_enabled
    await record_audit(
        session,
        actor=actor.id,
        action="admin.bank.update",
        target_type="bank_account",
        target_id=bank_id,
        ip=request.client.host if request.client else None,
        before=before,
        after={"polling_enabled": bank.polling_enabled},
    )
    await session.commit()
    return GenericMessage(message="ok")


@router.post("/bank-accounts/{bank_id}/rotate-credentials", response_model=GenericMessage)
async def admin_rotate_bank_credentials(
    bank_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
    username: str = Query(..., min_length=1, max_length=255),
    password: str = Query(..., min_length=1, max_length=255),
) -> GenericMessage:
    """Cập nhật credentials (encrypt qua Fernet) và clear last_error."""
    from packages.security.crypto import FernetCipher

    bank = await session.get(BankAccount, bank_id)
    if bank is None:
        raise HTTPException(status_code=404, detail="bank account not found")
    settings = get_settings()
    if not settings.fernet_keys:
        raise HTTPException(status_code=500, detail="fernet keys not configured")
    cipher = FernetCipher.from_keys(settings.fernet_keys)
    bank.credentials_enc = cipher.encrypt(f"{username}\n{password}")
    bank.last_error = None
    bank.polling_status = "idle"
    await record_audit(
        session,
        actor=actor.id,
        action="admin.bank.rotate_credentials",
        target_type="bank_account",
        target_id=bank_id,
        ip=request.client.host if request.client else None,
        after={"username_set": True},
    )
    await session.commit()
    return GenericMessage(message="rotated")


@router.post("/bank-accounts/{bank_id}/reset-cursor", response_model=GenericMessage)
async def admin_reset_poll_cursor(
    bank_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    from packages.db.models import PollCursor

    bank = await session.get(BankAccount, bank_id)
    if bank is None:
        raise HTTPException(status_code=404, detail="bank account not found")
    cursor = await session.get(PollCursor, bank_id)
    if cursor is not None:
        await session.delete(cursor)
    await record_audit(
        session,
        actor=actor.id,
        action="admin.bank.reset_cursor",
        target_type="bank_account",
        target_id=bank_id,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return GenericMessage(message="reset")


@router.delete("/bank-accounts/{bank_id}", response_model=GenericMessage)
async def admin_soft_delete_bank(
    bank_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    bank = await session.get(BankAccount, bank_id)
    if bank is None:
        raise HTTPException(status_code=404, detail="bank account not found")
    bank.status = "deleted"
    bank.polling_enabled = False
    await record_audit(
        session,
        actor=actor.id,
        action="admin.bank.delete",
        target_type="bank_account",
        target_id=bank_id,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return GenericMessage(message="deleted")


# ---------------------------------------------------------------------------
# STATS + AUDIT LOG
# ---------------------------------------------------------------------------


@router.get("/stats", response_model=AdminStats)
async def admin_stats(
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> AdminStats:
    now = datetime.now(UTC)
    last_24h = now - timedelta(hours=24)

    users_total = int(
        (await session.execute(select(func.count()).select_from(User))).scalar_one() or 0
    )
    users_active = int(
        (
            await session.execute(
                select(func.count()).select_from(User).where(User.status == "active")
            )
        ).scalar_one() or 0
    )
    orders_pending = int(
        (
            await session.execute(
                select(func.count()).select_from(Order).where(Order.status == "pending")
            )
        ).scalar_one() or 0
    )
    orders_paid_24h = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Order)
                .where(Order.status == "paid")
                .where(Order.paid_at >= last_24h)
            )
        ).scalar_one() or 0
    )
    tx_24h = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Transaction)
                .where(Transaction.posted_at >= last_24h)
            )
        ).scalar_one() or 0
    )
    wallet_total = (
        await session.execute(select(func.coalesce(func.sum(User.balance_vnd), 0)))
    ).scalar_one() or 0
    subs_active = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Subscription)
                .where(Subscription.status == "active")
            )
        ).scalar_one() or 0
    )
    bank_accounts = int(
        (
            await session.execute(
                select(func.count())
                .select_from(BankAccount)
                .where(BankAccount.status != "deleted")
            )
        ).scalar_one() or 0
    )

    last_30d = now - timedelta(days=30)
    revenue_30d = Decimal(
        (
            await session.execute(
                select(func.coalesce(func.sum(Invoice.amount_vnd), 0))
                .where(Invoice.status == "paid")
                .where(Invoice.issued_at >= last_30d)
            )
        ).scalar_one() or 0
    )
    # MRR = sum(price_vnd / duration_days * 30) cho subscription active còn hiệu lực
    mrr_rows = (
        await session.execute(
            select(Plan.price_vnd, Plan.duration_days)
            .select_from(Subscription)
            .join(Plan, Plan.id == Subscription.plan_id)
            .where(Subscription.status == "active")
            .where(Subscription.expires_at > now)
        )
    ).all()
    mrr = Decimal(0)
    for price, days in mrr_rows:
        if days and int(days) > 0:
            mrr += Decimal(price) * Decimal(30) / Decimal(int(days))
    mrr = mrr.quantize(Decimal("1"))

    api_keys_active = int(
        (
            await session.execute(
                select(func.count())
                .select_from(ApiKey)
                .where(ApiKey.revoked_at.is_(None))
            )
        ).scalar_one() or 0
    )
    today = now.date()
    requests_24h = int(
        (
            await session.execute(
                select(func.coalesce(func.sum(ApiUsageDaily.count), 0))
                .where(ApiUsageDaily.day == today)
            )
        ).scalar_one() or 0
    )

    return AdminStats(
        users_total=users_total,
        users_active=users_active,
        orders_pending=orders_pending,
        orders_paid_24h=orders_paid_24h,
        tx_24h=tx_24h,
        wallet_total_vnd=Decimal(wallet_total),
        subscriptions_active=subs_active,
        bank_accounts=bank_accounts,
        revenue_30d_vnd=revenue_30d,
        mrr_vnd=mrr,
        api_keys_active=api_keys_active,
        requests_24h=requests_24h,
    )


@router.get("/audit-log", response_model=AdminAuditResponse)
async def admin_audit_log(
    action: str | None = None,
    actor: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    ip: str | None = None,
    q: str | None = None,
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    cursor: str | None = Query(default=None, description="audit_log.id để keyset paginate"),
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> AdminAuditResponse:
    stmt = select(AuditLog)
    count_stmt = select(func.count()).select_from(AuditLog)
    if action:
        like = f"{action}%"
        stmt = stmt.where(AuditLog.action.like(like))
        count_stmt = count_stmt.where(AuditLog.action.like(like))
    if actor:
        stmt = stmt.where(AuditLog.actor == actor)
        count_stmt = count_stmt.where(AuditLog.actor == actor)
    if target_type:
        stmt = stmt.where(AuditLog.target_type == target_type)
        count_stmt = count_stmt.where(AuditLog.target_type == target_type)
    if target_id:
        stmt = stmt.where(AuditLog.target_id == target_id)
        count_stmt = count_stmt.where(AuditLog.target_id == target_id)
    if ip:
        stmt = stmt.where(AuditLog.ip == ip)
        count_stmt = count_stmt.where(AuditLog.ip == ip)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(AuditLog.action.ilike(like))
        count_stmt = count_stmt.where(AuditLog.action.ilike(like))
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= date_from)
        count_stmt = count_stmt.where(AuditLog.created_at >= date_from)
    if date_to:
        stmt = stmt.where(AuditLog.created_at <= date_to)
        count_stmt = count_stmt.where(AuditLog.created_at <= date_to)

    total = int((await session.execute(count_stmt)).scalar_one() or 0)
    if cursor:
        # Keyset pagination: chỉ trả các row có id < cursor (theo created_at desc).
        # Cursor là id của row cuối page trước.
        anchor = await session.get(AuditLog, cursor)
        if anchor is not None:
            stmt = stmt.where(AuditLog.created_at < anchor.created_at)
        offset = 0
    rows = list(
        (
            await session.scalars(
                stmt.order_by(desc(AuditLog.created_at)).limit(limit).offset(offset)
            )
        ).all()
    )
    return AdminAuditResponse(
        items=[
            AdminAuditItem.model_validate(r, from_attributes=True) for r in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# CONFIG: SMTP
# ---------------------------------------------------------------------------


SMTP_KEY = "smtp"
SMTP_ENC_FIELDS = ("password",)


@router.get("/config/smtp", response_model=SmtpConfigRead)
async def get_smtp_config(
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> SmtpConfigRead:
    # Dùng resolver để FE thấy ``.env`` SMTP nếu chưa save trong UI lần nào.
    resolved = await email_pkg.resolve_smtp(session)
    return SmtpConfigRead(
        host=resolved["host"],
        port=int(resolved["port"]),
        user=resolved["user"],
        from_addr=resolved["from_addr"] or "",
        use_tls=bool(resolved["use_tls"]),
        enabled=bool(resolved["enabled"]),
        password_set=bool(resolved["password_set"]),
    )


@router.put("/config/smtp", response_model=SmtpConfigRead)
async def update_smtp_config(
    payload: SmtpConfigUpdate,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> SmtpConfigRead:
    value: dict[str, Any] = payload.model_dump()
    await config_runtime.set_config(
        session, SMTP_KEY, value, actor_id=actor.id, encrypt_fields=SMTP_ENC_FIELDS
    )
    await record_audit(
        session,
        actor=actor.id,
        action="admin.config.update",
        target_type="app_config",
        target_id=SMTP_KEY,
        ip=request.client.host if request.client else None,
        after={
            "host": payload.host,
            "user": payload.user,
            "enabled": payload.enabled,
        },
    )
    await session.commit()
    return await get_smtp_config(actor, session)


@router.post("/config/smtp/test", response_model=SmtpTestResponse)
async def test_smtp(
    payload: SmtpTestRequest,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> SmtpTestResponse:
    ok, err = await email_pkg.send_email_test(to=str(payload.to_email), session=session)
    await record_audit(
        session,
        actor=actor.id,
        action="admin.config.smtp_test",
        target_type="app_config",
        target_id=SMTP_KEY,
        ip=request.client.host if request.client else None,
        after={"to": str(payload.to_email), "ok": ok},
    )
    await session.commit()
    return SmtpTestResponse(ok=ok, error=err)


# ---------------------------------------------------------------------------
# CONFIG: GOOGLE OAUTH
# ---------------------------------------------------------------------------


GOOGLE_KEY = "google_oauth"
GOOGLE_ENC_FIELDS = ("client_secret",)


@router.get("/config/google", response_model=GoogleConfigRead)
async def get_google_config(
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GoogleConfigRead:
    resolved = await oauth_google.resolve_google_oauth(session)
    return GoogleConfigRead(
        client_id=resolved["client_id"],
        redirect_uri=resolved["redirect_uri"],
        enabled=bool(resolved["enabled"]),
        client_secret_set=bool(resolved["client_secret_set"]),
    )


@router.put("/config/google", response_model=GoogleConfigRead)
async def update_google_config(
    payload: GoogleConfigUpdate,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GoogleConfigRead:
    value: dict[str, Any] = payload.model_dump()
    await config_runtime.set_config(
        session,
        GOOGLE_KEY,
        value,
        actor_id=actor.id,
        encrypt_fields=GOOGLE_ENC_FIELDS,
    )
    await record_audit(
        session,
        actor=actor.id,
        action="admin.config.update",
        target_type="app_config",
        target_id=GOOGLE_KEY,
        ip=request.client.host if request.client else None,
        after={
            "client_id_set": bool(payload.client_id),
            "redirect_uri": payload.redirect_uri,
            "enabled": payload.enabled,
        },
    )
    await session.commit()
    return await get_google_config(actor, session)


# ---------------------------------------------------------------------------
# CONFIG: TELEGRAM
# ---------------------------------------------------------------------------


TELEGRAM_KEY = "telegram"
TELEGRAM_ENC_FIELDS = ("bot_token",)
KIND_TG_LINK = "tg_link"


@router.get("/config/telegram", response_model=TelegramConfigRead)
async def get_telegram_config(
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> TelegramConfigRead:
    raw = await config_runtime.get_config(session, TELEGRAM_KEY)
    pub = config_runtime.public_view(raw, TELEGRAM_ENC_FIELDS)
    # Resolver biết cả `.env` fallback — đảm bảo FE nhìn thấy "đã configured"
    # ngay cả khi instance dùng APIBANK_TELEGRAM_BOT_TOKEN từ .env (chưa save
    # trong admin UI lần nào).
    resolved = await tg.resolve_telegram(session)
    return TelegramConfigRead(
        enabled=bool(resolved.get("enabled")),
        webhook_url=pub.get("webhook_url", ""),
        admin_chat_id=str(resolved.get("admin_chat_id") or ""),
        bot_username=pub.get("bot_username", ""),
        bot_token_set=bool(resolved.get("configured")),
    )


@router.put("/config/telegram", response_model=TelegramConfigRead)
async def update_telegram_config(
    payload: TelegramConfigUpdate,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> TelegramConfigRead:
    # Quy ước UX: nhập token mới → tự bật `enabled` (admin gần như luôn muốn
    # vậy; tránh tình trạng "đã save token mà user vẫn báo chưa configured"
    # vì admin quên toggle Switch). Admin vẫn có thể tắt rõ ràng bằng
    # ``payload.enabled = False`` nhưng kèm token rỗng.
    enabled_effective = payload.enabled or bool(payload.bot_token)
    value: dict[str, Any] = {"enabled": enabled_effective}
    if payload.bot_token is not None:
        value["bot_token"] = payload.bot_token
    await config_runtime.set_config(
        session,
        TELEGRAM_KEY,
        value,
        actor_id=actor.id,
        encrypt_fields=TELEGRAM_ENC_FIELDS,
    )

    # Nếu vừa cập nhật token, gọi getMe để lưu bot_username
    if payload.bot_token:
        try:
            info = await tg.get_me(payload.bot_token)
            if info.get("ok"):
                username = (info.get("result") or {}).get("username") or ""
                cfg = await config_runtime.get_config(session, TELEGRAM_KEY)
                cfg["bot_username"] = username
                await config_runtime.set_config(
                    session,
                    TELEGRAM_KEY,
                    cfg,
                    actor_id=actor.id,
                    encrypt_fields=TELEGRAM_ENC_FIELDS,
                )
        except Exception:  # noqa: BLE001
            logger.exception("telegram_getme_failed")

    await record_audit(
        session,
        actor=actor.id,
        action="admin.config.update",
        target_type="app_config",
        target_id=TELEGRAM_KEY,
        ip=request.client.host if request.client else None,
        after={"enabled": enabled_effective, "bot_token_changed": bool(payload.bot_token)},
    )
    await session.commit()
    return await get_telegram_config(actor, session)


@router.post(
    "/config/telegram/register-webhook",
    response_model=TelegramRegisterWebhookResponse,
)
async def register_telegram_webhook(
    payload: TelegramRegisterWebhookRequest,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> TelegramRegisterWebhookResponse:
    cfg = await tg.resolve_telegram(session)
    token = cfg["token"]
    if not token:
        raise HTTPException(status_code=400, detail="bot token not set")
    base = payload.base_url.rstrip("/")
    webhook_url = f"{base}/api/v1/telegram/webhook"
    secret_token = secrets.token_urlsafe(24)

    result = await tg.set_webhook(token, webhook_url, secret_token=secret_token)
    ok = bool(result.get("ok"))
    if ok:
        cfg_raw = await config_runtime.get_config(session, TELEGRAM_KEY)
        cfg_raw["webhook_url"] = webhook_url
        cfg_raw["webhook_secret"] = secret_token
        await config_runtime.set_config(
            session,
            TELEGRAM_KEY,
            cfg_raw,
            actor_id=actor.id,
            encrypt_fields=TELEGRAM_ENC_FIELDS,
        )
    await record_audit(
        session,
        actor=actor.id,
        action="admin.telegram.register_webhook",
        target_type="app_config",
        target_id=TELEGRAM_KEY,
        ip=request.client.host if request.client else None,
        after={"ok": ok, "webhook_url": webhook_url},
    )
    await session.commit()
    return TelegramRegisterWebhookResponse(
        ok=ok,
        description=result.get("description"),
        webhook_url=webhook_url if ok else None,
    )


@router.delete("/config/telegram/webhook", response_model=GenericMessage)
async def delete_telegram_webhook(
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    cfg = await tg.resolve_telegram(session)
    token = cfg["token"]
    if token:
        await tg.delete_webhook(token)
    cfg_raw = await config_runtime.get_config(session, TELEGRAM_KEY)
    cfg_raw["webhook_url"] = ""
    cfg_raw["webhook_secret"] = ""
    await config_runtime.set_config(
        session,
        TELEGRAM_KEY,
        cfg_raw,
        actor_id=actor.id,
        encrypt_fields=TELEGRAM_ENC_FIELDS,
    )
    await record_audit(
        session,
        actor=actor.id,
        action="admin.telegram.delete_webhook",
        target_type="app_config",
        target_id=TELEGRAM_KEY,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return GenericMessage(message="webhook removed")


@router.post("/config/telegram/link-chat", response_model=TelegramLinkChatResponse)
async def link_telegram_chat(
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> TelegramLinkChatResponse:
    cfg = await tg.resolve_telegram(session)
    if not cfg["configured"]:
        raise HTTPException(status_code=400, detail="bot token not set")
    bot_username = cfg.get("bot_username") or ""
    if not bot_username:
        # Fetch lại nếu thiếu
        info = await tg.get_me(cfg["token"])
        if info.get("ok"):
            bot_username = (info.get("result") or {}).get("username") or ""
            cfg_raw = await config_runtime.get_config(session, TELEGRAM_KEY)
            cfg_raw["bot_username"] = bot_username
            await config_runtime.set_config(
                session,
                TELEGRAM_KEY,
                cfg_raw,
                actor_id=actor.id,
                encrypt_fields=TELEGRAM_ENC_FIELDS,
            )

    if not bot_username:
        raise HTTPException(status_code=502, detail="cannot resolve bot username")

    raw = generate_token(20)
    token_record = EmailToken(
        user_id=actor.id,
        kind=KIND_TG_LINK,
        token_hash=hash_token(raw),
        expires_at=utcnow() + timedelta(minutes=10),
    )
    session.add(token_record)
    await session.commit()
    return TelegramLinkChatResponse(
        deep_link_url=f"https://t.me/{bot_username}?start={raw}",
        token=raw,
        expires_in=600,
    )


@router.delete("/config/telegram/admin-chat", response_model=GenericMessage)
async def unlink_telegram_chat(
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    cfg_raw = await config_runtime.get_config(session, TELEGRAM_KEY)
    cfg_raw["admin_chat_id"] = ""
    await config_runtime.set_config(
        session,
        TELEGRAM_KEY,
        cfg_raw,
        actor_id=actor.id,
        encrypt_fields=TELEGRAM_ENC_FIELDS,
    )
    await record_audit(
        session,
        actor=actor.id,
        action="admin.telegram.unlink_chat",
        target_type="app_config",
        target_id=TELEGRAM_KEY,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return GenericMessage(message="ok")


# ---------------------------------------------------------------------------
# API KEYS (admin)
# ---------------------------------------------------------------------------


_ADMIN_ALLOWED_SCOPES = {
    "orders:read",
    "orders:write",
    "transactions:read",
    "webhooks:read",
    "bank_accounts:read",
    "admin:*",
}


def _api_key_to_read(record: ApiKey, *, user_email: str | None) -> AdminApiKeyRead:
    return AdminApiKeyRead(
        id=record.id,
        user_id=record.user_id,
        user_email=user_email,
        name=record.name,
        scopes=list(record.scopes or []),
        last_used_at=record.last_used_at,
        last_used_ip=record.last_used_ip,
        expires_at=record.expires_at,
        revoked_at=record.revoked_at,
        created_at=record.created_at,
    )


@router.get("/api-keys", response_model=AdminApiKeyListResponse)
async def admin_list_api_keys(
    user_id: str | None = None,
    q: str | None = None,
    revoked: bool | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> AdminApiKeyListResponse:
    stmt = select(ApiKey, User.email).outerjoin(User, ApiKey.user_id == User.id)
    count_stmt = select(func.count()).select_from(ApiKey).outerjoin(
        User, ApiKey.user_id == User.id
    )
    if user_id:
        stmt = stmt.where(ApiKey.user_id == user_id)
        count_stmt = count_stmt.where(ApiKey.user_id == user_id)
    if revoked is True:
        stmt = stmt.where(ApiKey.revoked_at.is_not(None))
        count_stmt = count_stmt.where(ApiKey.revoked_at.is_not(None))
    elif revoked is False:
        stmt = stmt.where(ApiKey.revoked_at.is_(None))
        count_stmt = count_stmt.where(ApiKey.revoked_at.is_(None))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(User.email.ilike(like), ApiKey.name.ilike(like)))
        count_stmt = count_stmt.where(
            or_(User.email.ilike(like), ApiKey.name.ilike(like))
        )

    total = int((await session.execute(count_stmt)).scalar_one() or 0)
    stmt = stmt.order_by(desc(ApiKey.created_at)).limit(limit).offset(offset)
    rows = (await session.execute(stmt)).all()
    items = [_api_key_to_read(r, user_email=email) for r, email in rows]
    return AdminApiKeyListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/users/{user_id}/api-keys", response_model=list[AdminApiKeyRead]
)
async def admin_list_user_api_keys(
    user_id: str,
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> list[AdminApiKeyRead]:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    rows = list(
        (
            await session.scalars(
                select(ApiKey)
                .where(ApiKey.user_id == user_id)
                .order_by(desc(ApiKey.created_at))
            )
        ).all()
    )
    return [_api_key_to_read(r, user_email=user.email) for r in rows]


@router.post(
    "/users/{user_id}/api-keys",
    response_model=AdminApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
)
async def admin_create_user_api_key(
    user_id: str,
    payload: AdminApiKeyCreate,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> AdminApiKeyCreated:
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    invalid = [s for s in payload.scopes if s not in _ADMIN_ALLOWED_SCOPES]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid scopes: {invalid}",
        )
    raw = generate_api_key()
    digest = hash_api_key(raw, salt=get_settings().api_key_salt)
    record = ApiKey(
        owner_id=target.id,
        user_id=target.id,
        name=payload.name,
        key_hash=digest,
        scopes=list(payload.scopes),
        expires_at=payload.expires_at,
    )
    session.add(record)
    await session.flush()
    await record_audit(
        session,
        actor=actor.id,
        action="admin.apikey.create",
        target_type="api_key",
        target_id=record.id,
        ip=request.client.host if request.client else None,
        after={"user_id": target.id, "name": payload.name, "scopes": payload.scopes},
    )
    await session.commit()
    base = _api_key_to_read(record, user_email=target.email).model_dump()
    return AdminApiKeyCreated(**base, raw_key=raw)


@router.post("/api-keys/{api_key_id}/revoke", response_model=GenericMessage)
async def admin_revoke_api_key(
    api_key_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    record = await session.get(ApiKey, api_key_id)
    if record is None:
        raise HTTPException(status_code=404, detail="api key not found")
    if record.revoked_at is None:
        record.revoked_at = datetime.now(UTC)
    await record_audit(
        session,
        actor=actor.id,
        action="admin.apikey.revoke",
        target_type="api_key",
        target_id=record.id,
        ip=request.client.host if request.client else None,
        after={"user_id": record.user_id},
    )
    await session.commit()
    return GenericMessage(message="revoked")


# ---------------------------------------------------------------------------
# USAGE ANALYTICS
# ---------------------------------------------------------------------------


def _normalize_days(days: int) -> int:
    if days < 1:
        return 1
    if days > 365:
        return 365
    return days


@router.get("/usage/summary", response_model=AdminUsageSummary)
async def admin_usage_summary(
    days: int = Query(7, ge=1, le=365),
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> AdminUsageSummary:
    days = _normalize_days(days)
    today = datetime.now(UTC).date()
    since = today - timedelta(days=days - 1)

    totals_row = (
        await session.execute(
            select(
                func.coalesce(func.sum(ApiUsageDaily.count), 0),
                func.coalesce(func.sum(ApiUsageDaily.error_count), 0),
                func.count(func.distinct(ApiUsageDaily.user_id)),
                func.count(func.distinct(ApiUsageDaily.api_key_id)),
            ).where(ApiUsageDaily.day >= since)
        )
    ).first()
    total_count = int(totals_row[0] or 0) if totals_row else 0
    total_errors = int(totals_row[1] or 0) if totals_row else 0
    unique_users = int(totals_row[2] or 0) if totals_row else 0
    unique_keys = int(totals_row[3] or 0) if totals_row else 0

    top_endpoints_rows = (
        await session.execute(
            select(
                ApiUsageDaily.endpoint_group,
                func.sum(ApiUsageDaily.count).label("c"),
                func.sum(ApiUsageDaily.error_count).label("e"),
            )
            .where(ApiUsageDaily.day >= since)
            .group_by(ApiUsageDaily.endpoint_group)
            .order_by(desc("c"))
            .limit(5)
        )
    ).all()
    top_endpoints = [
        AdminUsageEndpointRow(
            endpoint_group=r[0], count=int(r[1] or 0), error_count=int(r[2] or 0)
        )
        for r in top_endpoints_rows
    ]

    top_users_rows = (
        await session.execute(
            select(
                ApiUsageDaily.user_id,
                User.email,
                func.sum(ApiUsageDaily.count).label("c"),
                func.sum(ApiUsageDaily.error_count).label("e"),
            )
            .select_from(ApiUsageDaily)
            .outerjoin(User, User.id == ApiUsageDaily.user_id)
            .where(ApiUsageDaily.day >= since)
            .group_by(ApiUsageDaily.user_id, User.email)
            .order_by(desc("c"))
            .limit(5)
        )
    ).all()
    top_users = [
        AdminUsageUserRow(
            user_id=r[0],
            user_email=r[1],
            count=int(r[2] or 0),
            error_count=int(r[3] or 0),
        )
        for r in top_users_rows
    ]

    return AdminUsageSummary(
        days=days,
        total_count=total_count,
        total_errors=total_errors,
        unique_users=unique_users,
        unique_api_keys=unique_keys,
        top_endpoints=top_endpoints,
        top_users=top_users,
    )


def _build_daily_series(
    rows: list[tuple[Any, int, int]], *, days: int, since: Any
) -> list[AdminUsageDailyPoint]:
    bucket: dict[str, tuple[int, int]] = {}
    for day_val, cnt, err in rows:
        key = day_val.isoformat() if hasattr(day_val, "isoformat") else str(day_val)
        bucket[key] = (int(cnt or 0), int(err or 0))
    points: list[AdminUsageDailyPoint] = []
    for i in range(days):
        d = since + timedelta(days=i)
        key = d.isoformat()
        cnt, err = bucket.get(key, (0, 0))
        points.append(AdminUsageDailyPoint(day=key, count=cnt, error_count=err))
    return points


@router.get("/usage/timeseries", response_model=AdminUsageTimeseries)
async def admin_usage_timeseries(
    days: int = Query(30, ge=1, le=365),
    user_id: str | None = None,
    api_key_id: str | None = None,
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> AdminUsageTimeseries:
    days = _normalize_days(days)
    today = datetime.now(UTC).date()
    since = today - timedelta(days=days - 1)
    stmt = (
        select(
            ApiUsageDaily.day,
            func.sum(ApiUsageDaily.count),
            func.sum(ApiUsageDaily.error_count),
        )
        .where(ApiUsageDaily.day >= since)
        .group_by(ApiUsageDaily.day)
        .order_by(ApiUsageDaily.day)
    )
    if user_id:
        stmt = stmt.where(ApiUsageDaily.user_id == user_id)
    if api_key_id:
        stmt = stmt.where(ApiUsageDaily.api_key_id == api_key_id)
    rows = (await session.execute(stmt)).all()
    points = _build_daily_series(
        [(r[0], r[1], r[2]) for r in rows], days=days, since=since
    )
    return AdminUsageTimeseries(
        days=days, user_id=user_id, api_key_id=api_key_id, points=points
    )


@router.get("/users/{user_id}/usage", response_model=AdminUserUsageDetail)
async def admin_user_usage(
    user_id: str,
    days: int = Query(30, ge=1, le=365),
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> AdminUserUsageDetail:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    days = _normalize_days(days)
    today = datetime.now(UTC).date()
    since = today - timedelta(days=days - 1)

    daily_rows = (
        await session.execute(
            select(
                ApiUsageDaily.day,
                func.sum(ApiUsageDaily.count),
                func.sum(ApiUsageDaily.error_count),
            )
            .where(ApiUsageDaily.user_id == user_id)
            .where(ApiUsageDaily.day >= since)
            .group_by(ApiUsageDaily.day)
            .order_by(ApiUsageDaily.day)
        )
    ).all()
    points = _build_daily_series(
        [(r[0], r[1], r[2]) for r in daily_rows], days=days, since=since
    )

    by_key_rows = (
        await session.execute(
            select(
                ApiUsageDaily.api_key_id,
                ApiKey.name,
                func.sum(ApiUsageDaily.count),
                func.sum(ApiUsageDaily.error_count),
            )
            .select_from(ApiUsageDaily)
            .outerjoin(ApiKey, ApiKey.id == ApiUsageDaily.api_key_id)
            .where(ApiUsageDaily.user_id == user_id)
            .where(ApiUsageDaily.day >= since)
            .group_by(ApiUsageDaily.api_key_id, ApiKey.name)
            .order_by(desc(func.sum(ApiUsageDaily.count)))
        )
    ).all()
    by_api_key = [
        AdminUsageApiKeyBreakdown(
            api_key_id=r[0], name=r[1], count=int(r[2] or 0), error_count=int(r[3] or 0)
        )
        for r in by_key_rows
    ]

    by_endpoint_rows = (
        await session.execute(
            select(
                ApiUsageDaily.endpoint_group,
                func.sum(ApiUsageDaily.count),
                func.sum(ApiUsageDaily.error_count),
            )
            .where(ApiUsageDaily.user_id == user_id)
            .where(ApiUsageDaily.day >= since)
            .group_by(ApiUsageDaily.endpoint_group)
            .order_by(desc(func.sum(ApiUsageDaily.count)))
        )
    ).all()
    by_endpoint = [
        AdminUsageEndpointRow(
            endpoint_group=r[0], count=int(r[1] or 0), error_count=int(r[2] or 0)
        )
        for r in by_endpoint_rows
    ]

    total_count = sum(p.count for p in points)
    total_errors = sum(p.error_count for p in points)
    return AdminUserUsageDetail(
        user_id=user_id,
        days=days,
        total_count=total_count,
        total_errors=total_errors,
        points=points,
        by_api_key=by_api_key,
        by_endpoint=by_endpoint,
    )


# ---------------------------------------------------------------------------
# REVENUE
# ---------------------------------------------------------------------------


@router.get("/revenue/summary", response_model=AdminRevenueSummary)
async def admin_revenue_summary(
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> AdminRevenueSummary:
    now = datetime.now(UTC)
    today_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    last_30d = now - timedelta(days=30)

    today_vnd = Decimal(
        (
            await session.execute(
                select(func.coalesce(func.sum(Invoice.amount_vnd), 0))
                .where(Invoice.status == "paid")
                .where(Invoice.issued_at >= today_start)
            )
        ).scalar_one() or 0
    )
    this_month_vnd = Decimal(
        (
            await session.execute(
                select(func.coalesce(func.sum(Invoice.amount_vnd), 0))
                .where(Invoice.status == "paid")
                .where(Invoice.issued_at >= month_start)
            )
        ).scalar_one() or 0
    )
    last_30d_vnd = Decimal(
        (
            await session.execute(
                select(func.coalesce(func.sum(Invoice.amount_vnd), 0))
                .where(Invoice.status == "paid")
                .where(Invoice.issued_at >= last_30d)
            )
        ).scalar_one() or 0
    )
    total_invoices = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Invoice)
                .where(Invoice.status == "paid")
            )
        ).scalar_one() or 0
    )
    topup_30d = Decimal(
        (
            await session.execute(
                select(func.coalesce(func.sum(WalletTransaction.amount_vnd), 0))
                .where(WalletTransaction.type == "topup")
                .where(WalletTransaction.created_at >= last_30d)
            )
        ).scalar_one() or 0
    )
    refund_30d_raw = Decimal(
        (
            await session.execute(
                select(func.coalesce(func.sum(WalletTransaction.amount_vnd), 0))
                .where(WalletTransaction.type == "refund")
                .where(WalletTransaction.created_at >= last_30d)
            )
        ).scalar_one() or 0
    )
    refund_30d = abs(refund_30d_raw)
    discount_30d = Decimal(
        (
            await session.execute(
                select(func.coalesce(func.sum(Invoice.discount_vnd), 0))
                .where(Invoice.status == "paid")
                .where(Invoice.issued_at >= last_30d)
            )
        ).scalar_one() or 0
    )

    mrr_rows = (
        await session.execute(
            select(Plan.price_vnd, Plan.duration_days)
            .select_from(Subscription)
            .join(Plan, Plan.id == Subscription.plan_id)
            .where(Subscription.status == "active")
            .where(Subscription.expires_at > now)
        )
    ).all()
    mrr = Decimal(0)
    for price, days_ in mrr_rows:
        if days_ and int(days_) > 0:
            mrr += Decimal(price) * Decimal(30) / Decimal(int(days_))
    mrr = mrr.quantize(Decimal("1"))

    return AdminRevenueSummary(
        today_vnd=today_vnd,
        this_month_vnd=this_month_vnd,
        last_30d_vnd=last_30d_vnd,
        mrr_vnd=mrr,
        total_invoices_paid=total_invoices,
        topup_vnd_30d=topup_30d,
        refund_vnd_30d=refund_30d,
        discount_vnd_30d=discount_30d,
    )


@router.get("/revenue/timeseries", response_model=AdminRevenueTimeseries)
async def admin_revenue_timeseries(
    days: int = Query(30, ge=1, le=365),
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> AdminRevenueTimeseries:
    days = _normalize_days(days)
    now = datetime.now(UTC)
    today = now.date()
    since_day = today - timedelta(days=days - 1)
    since_dt = datetime(since_day.year, since_day.month, since_day.day, tzinfo=UTC)

    inv_rows = (
        await session.execute(
            select(
                func.date(Invoice.issued_at).label("d"),
                func.coalesce(func.sum(Invoice.amount_vnd), 0),
                func.coalesce(func.sum(Invoice.discount_vnd), 0),
            )
            .where(Invoice.status == "paid")
            .where(Invoice.issued_at >= since_dt)
            .group_by("d")
        )
    ).all()
    topup_rows = (
        await session.execute(
            select(
                func.date(WalletTransaction.created_at).label("d"),
                func.coalesce(func.sum(WalletTransaction.amount_vnd), 0),
            )
            .where(WalletTransaction.type == "topup")
            .where(WalletTransaction.created_at >= since_dt)
            .group_by("d")
        )
    ).all()
    refund_rows = (
        await session.execute(
            select(
                func.date(WalletTransaction.created_at).label("d"),
                func.coalesce(func.sum(WalletTransaction.amount_vnd), 0),
            )
            .where(WalletTransaction.type == "refund")
            .where(WalletTransaction.created_at >= since_dt)
            .group_by("d")
        )
    ).all()

    def _to_iso_key(v: Any) -> str:
        if hasattr(v, "isoformat"):
            return str(v.isoformat())
        return str(v)

    inv_map = {_to_iso_key(r[0]): (Decimal(r[1] or 0), Decimal(r[2] or 0)) for r in inv_rows}
    topup_map = {_to_iso_key(r[0]): Decimal(r[1] or 0) for r in topup_rows}
    refund_map = {_to_iso_key(r[0]): Decimal(r[1] or 0) for r in refund_rows}

    points: list[AdminRevenuePoint] = []
    for i in range(days):
        d = since_day + timedelta(days=i)
        key = d.isoformat()
        sub_amt, disc_amt = inv_map.get(key, (Decimal(0), Decimal(0)))
        topup = topup_map.get(key, Decimal(0))
        refund = abs(refund_map.get(key, Decimal(0)))
        net = sub_amt + topup - refund
        points.append(
            AdminRevenuePoint(
                day=key,
                subscription_vnd=sub_amt,
                topup_vnd=topup,
                refund_vnd=refund,
                discount_vnd=disc_amt,
                net_vnd=net,
            )
        )
    return AdminRevenueTimeseries(days=days, points=points)


@router.get("/revenue/by-plan", response_model=list[AdminRevenueByPlanRow])
async def admin_revenue_by_plan(
    days: int = Query(30, ge=1, le=365),
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> list[AdminRevenueByPlanRow]:
    days = _normalize_days(days)
    now = datetime.now(UTC)
    since = now - timedelta(days=days)
    rows = (
        await session.execute(
            select(
                Invoice.plan_code,
                func.count(Invoice.id),
                func.coalesce(func.sum(Invoice.amount_vnd), 0),
                func.coalesce(func.sum(Invoice.discount_vnd), 0),
            )
            .where(Invoice.status == "paid")
            .where(Invoice.issued_at >= since)
            .group_by(Invoice.plan_code)
            .order_by(desc(func.sum(Invoice.amount_vnd)))
        )
    ).all()
    return [
        AdminRevenueByPlanRow(
            plan_code=r[0],
            invoices=int(r[1] or 0),
            gross_vnd=Decimal(r[2] or 0) + Decimal(r[3] or 0),
            discount_vnd=Decimal(r[3] or 0),
            net_vnd=Decimal(r[2] or 0),
        )
        for r in rows
    ]


@router.get("/revenue/by-coupon", response_model=list[AdminRevenueByCouponRow])
async def admin_revenue_by_coupon(
    days: int = Query(30, ge=1, le=365),
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> list[AdminRevenueByCouponRow]:
    days = _normalize_days(days)
    now = datetime.now(UTC)
    since = now - timedelta(days=days)
    rows = (
        await session.execute(
            select(
                Invoice.coupon_code,
                func.count(Invoice.id),
                func.coalesce(func.sum(Invoice.discount_vnd), 0),
                func.coalesce(func.sum(Invoice.amount_vnd), 0),
            )
            .where(Invoice.status == "paid")
            .where(Invoice.coupon_code.is_not(None))
            .where(Invoice.issued_at >= since)
            .group_by(Invoice.coupon_code)
            .order_by(desc(func.sum(Invoice.discount_vnd)))
        )
    ).all()
    return [
        AdminRevenueByCouponRow(
            coupon_code=r[0],
            redemptions=int(r[1] or 0),
            discount_vnd=Decimal(r[2] or 0),
            net_vnd=Decimal(r[3] or 0),
        )
        for r in rows
    ]


@router.get("/invoices", response_model=AdminInvoiceListResponse)
async def admin_list_invoices(
    user_id: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    plan_code: str | None = None,
    coupon_code: str | None = None,
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> AdminInvoiceListResponse:
    stmt = select(Invoice, User.email).outerjoin(User, User.id == Invoice.user_id)
    count_stmt = select(func.count()).select_from(Invoice)
    if user_id:
        stmt = stmt.where(Invoice.user_id == user_id)
        count_stmt = count_stmt.where(Invoice.user_id == user_id)
    if status_filter:
        stmt = stmt.where(Invoice.status == status_filter)
        count_stmt = count_stmt.where(Invoice.status == status_filter)
    if plan_code:
        stmt = stmt.where(Invoice.plan_code == plan_code)
        count_stmt = count_stmt.where(Invoice.plan_code == plan_code)
    if coupon_code:
        stmt = stmt.where(Invoice.coupon_code == coupon_code)
        count_stmt = count_stmt.where(Invoice.coupon_code == coupon_code)
    if date_from:
        stmt = stmt.where(Invoice.issued_at >= date_from)
        count_stmt = count_stmt.where(Invoice.issued_at >= date_from)
    if date_to:
        stmt = stmt.where(Invoice.issued_at <= date_to)
        count_stmt = count_stmt.where(Invoice.issued_at <= date_to)

    total = int((await session.execute(count_stmt)).scalar_one() or 0)
    stmt = stmt.order_by(desc(Invoice.issued_at)).limit(limit).offset(offset)
    rows = (await session.execute(stmt)).all()
    items = [
        AdminInvoiceRead(
            id=r.id,
            user_id=r.user_id,
            user_email=email,
            plan_code=r.plan_code,
            amount_vnd=Decimal(r.amount_vnd),
            currency=r.currency,
            status=r.status,
            coupon_code=r.coupon_code,
            discount_vnd=Decimal(r.discount_vnd or 0),
            original_amount_vnd=(
                Decimal(r.original_amount_vnd)
                if r.original_amount_vnd is not None
                else None
            ),
            issued_at=r.issued_at,
        )
        for r, email in rows
    ]
    return AdminInvoiceListResponse(
        items=items, total=total, limit=limit, offset=offset
    )


__all__ = ["router"]
_ = ApiKey  # giữ import cho audit hover
