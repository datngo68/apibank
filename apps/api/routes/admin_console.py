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
from packages.db.models import (
    ApiKey,
    AuditLog,
    BankAccount,
    EmailToken,
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
    AdminAuditItem,
    AdminAuditResponse,
    AdminBankAccountRead,
    AdminPlanCreate,
    AdminPlanRead,
    AdminPlanUpdate,
    AdminStats,
    AdminSystemBankSet,
    AdminUserDetail,
    AdminUserListItem,
    AdminUserListResponse,
    AdminUserUpdate,
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
        subscription=sub_payload,
        recent_wallet_tx=recent_tx,
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

    await record_audit(
        session,
        actor=actor.id,
        action="admin.user.update",
        target_type="user",
        target_id=user.id,
        ip=request.client.host if request.client else None,
        before=before,
        after={"role": user.role, "status": user.status, "full_name": user.full_name},
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

    return AdminStats(
        users_total=users_total,
        users_active=users_active,
        orders_pending=orders_pending,
        orders_paid_24h=orders_paid_24h,
        tx_24h=tx_24h,
        wallet_total_vnd=Decimal(wallet_total),
        subscriptions_active=subs_active,
        bank_accounts=bank_accounts,
    )


@router.get("/audit-log", response_model=AdminAuditResponse)
async def admin_audit_log(
    action: str | None = None,
    actor: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
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
    total = int((await session.execute(count_stmt)).scalar_one() or 0)
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
    raw = await config_runtime.get_config(session, SMTP_KEY)
    pub = config_runtime.public_view(raw, SMTP_ENC_FIELDS)
    return SmtpConfigRead(
        host=pub.get("host", ""),
        port=int(pub.get("port", 587) or 587),
        user=pub.get("user", ""),
        from_addr=pub.get("from_addr", ""),
        use_tls=bool(pub.get("use_tls", True)),
        enabled=bool(pub.get("enabled", False)),
        password_set=bool(pub.get("password_set", False)),
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
    raw = await config_runtime.get_config(session, GOOGLE_KEY)
    pub = config_runtime.public_view(raw, GOOGLE_ENC_FIELDS)
    return GoogleConfigRead(
        client_id=pub.get("client_id", ""),
        redirect_uri=pub.get("redirect_uri", ""),
        enabled=bool(pub.get("enabled", False)),
        client_secret_set=bool(pub.get("client_secret_set", False)),
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
    return TelegramConfigRead(
        enabled=bool(pub.get("enabled", False)),
        webhook_url=pub.get("webhook_url", ""),
        admin_chat_id=str(pub.get("admin_chat_id") or ""),
        bot_username=pub.get("bot_username", ""),
        bot_token_set=bool(pub.get("bot_token_set", False)),
    )


@router.put("/config/telegram", response_model=TelegramConfigRead)
async def update_telegram_config(
    payload: TelegramConfigUpdate,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> TelegramConfigRead:
    value: dict[str, Any] = {"enabled": payload.enabled}
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
        after={"enabled": payload.enabled},
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
    cfg = await config_runtime.get_decrypted(
        session, TELEGRAM_KEY, TELEGRAM_ENC_FIELDS
    )
    token = cfg.get("bot_token") or ""
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
    cfg = await config_runtime.get_decrypted(
        session, TELEGRAM_KEY, TELEGRAM_ENC_FIELDS
    )
    token = cfg.get("bot_token") or ""
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
    cfg = await config_runtime.get_decrypted(
        session, TELEGRAM_KEY, TELEGRAM_ENC_FIELDS
    )
    if not cfg.get("bot_token"):
        raise HTTPException(status_code=400, detail="bot token not set")
    bot_username = cfg.get("bot_username") or ""
    if not bot_username:
        # Fetch lại nếu thiếu
        info = await tg.get_me(cfg["bot_token"])
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


__all__ = ["router"]
_ = ApiKey  # giữ import cho audit hover
