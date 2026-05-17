"""Routes /api/v1/me/* — multi-tenant API cho người dùng.

Mỗi endpoint:
- Yêu cầu cookie session (Depends(current_user)).
- Resource scope theo user_id để tránh truy cập chéo.
- Audit log cho thao tác nhạy cảm.
"""

from __future__ import annotations

import asyncio
import secrets
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.banks import poll_kick
from packages.billing import subscription as subscription_pkg
from packages.billing import topup as topup_pkg
from packages.billing import wallet as wallet_pkg
from packages.billing.errors import (
    InsufficientFundsError,
    PlanNotFoundError,
    SystemBankNotConfiguredError,
)
from packages.config.settings import get_settings
from packages.db.models import (
    ApiKey,
    BankAccount,
    Invoice,
    Notification,
    NotificationPreference,
    Order,
    Plan,
    Transaction,
    User,
    Webhook,
    WebhookAttempt,
    utcnow,
)
from packages.db.session import get_session
from packages.qr.vietqr import vietqr_image_url
from packages.schemas.auth import GenericMessage
from packages.schemas.me import (
    VALID_NOTIFICATION_CHANNELS,
    BankAccountCreate,
    BankAccountRead,
    BankAccountRotate,
    BankAccountUpdate,
    InvoiceRead,
    MeApiKeyCreate,
    MeApiKeyCreated,
    MeApiKeyRead,
    MeWebhookCreate,
    MeWebhookRead,
    MeWebhookUpdate,
    NotificationPreferenceItem,
    NotificationPreferenceList,
    NotificationPreferenceUpdate,
    NotificationRead,
    NotificationUnreadCount,
    OrderListItem,
    PlanRead,
    SubscriptionPurchaseRequest,
    SubscriptionRead,
    TopupCheckResponse,
    TopupCreateRequest,
    TopupListItem,
    TopupResponse,
    TransactionListItem,
    WalletBalanceRead,
    WalletTransactionRead,
)
from packages.security.api_keys import generate_api_key, hash_api_key
from packages.security.audit import record_audit
from packages.security.crypto import FernetCipher
from packages.security.user_auth import current_user
from packages.webhook import (
    encrypt_webhook_secret,
    validate_webhook_url,
)

router = APIRouter(prefix="/api/v1/me", tags=["me"])
public_router = APIRouter(prefix="/api/v1", tags=["public"])


_BANK_NAME: dict[str, str] = {
    "MB": "MB Bank",
    "BIDV": "BIDV",
    "ACB": "ACB",
    "VCB": "Vietcombank",
    "TCB": "Techcombank",
    "VPB": "VPBank",
    "TPB": "TPBank",
    "ICB": "Vietinbank",
    "VBA": "Agribank",
    "STB": "Sacombank",
}


def _cipher() -> FernetCipher | None:
    keys = get_settings().fernet_keys
    return FernetCipher.from_keys(keys) if keys else None


def _require_cipher() -> FernetCipher:
    cipher = _cipher()
    if cipher is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="server missing APIBANK_FERNET_KEYS",
        )
    return cipher


# ---------------------------------------------------------------------------
# BANK ACCOUNTS
# ---------------------------------------------------------------------------


@router.get("/bank-accounts", response_model=list[BankAccountRead])
async def list_bank_accounts(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[BankAccountRead]:
    rows = list(
        (
            await session.scalars(
                select(BankAccount)
                .where(BankAccount.user_id == user.id)
                .where(BankAccount.status != "deleted")
                .order_by(BankAccount.created_at.desc())
            )
        ).all()
    )
    return [BankAccountRead.model_validate(r, from_attributes=True) for r in rows]


@router.post("/bank-accounts", response_model=BankAccountRead, status_code=status.HTTP_201_CREATED)
async def create_bank_account(
    payload: BankAccountCreate,
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> BankAccountRead:
    from packages.banks.registry import UNSUPPORTED_BANKS

    bank_code = payload.bank_code.upper()
    if bank_code in UNSUPPORTED_BANKS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Ngân hàng {bank_code} chưa được hỗ trợ trong phiên bản này; "
                "chỉ MB và Vietinbank đang khả dụng."
            ),
        )
    cipher = _require_cipher()
    account = BankAccount(
        user_id=user.id,
        bank_code=bank_code,
        account_no=payload.account_no,
        account_holder=payload.account_holder,
        credentials_enc=cipher.encrypt(f"{payload.username}:{payload.password}"),
        status="active",
        polling_enabled=True,
        polling_status="idle",
    )
    session.add(account)
    await session.flush()
    await record_audit(
        session,
        actor=user.id,
        action="bank.create",
        target_type="bank_account",
        target_id=account.id,
        ip=request.client.host if request.client else None,
        after={"bank_code": account.bank_code, "account_no": account.account_no},
    )
    await session.commit()
    # Kick worker rescan để pickup bank mới ngay (best-effort, no-op nếu Redis down).
    try:
        from packages.infra_pubsub import publish

        await publish("bank:account:added", account.id)
    except Exception:  # noqa: BLE001, S110
        pass
    return BankAccountRead.model_validate(account, from_attributes=True)


@router.post(
    "/bank-accounts/{bank_account_id}/verify", response_model=BankAccountRead
)
async def verify_bank_account(
    bank_account_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> BankAccountRead:
    """Thử login bank ngay với credential đã lưu.

    Nếu OK: set ``verified_at = now``, trả 200 + bank record (UI hiện tích xanh).
    Nếu fail: lưu ``last_error``, trả 422 với chi tiết để user sửa credential.
    """
    from packages.banks.base import BankAuthError, BankRateLimited
    from packages.banks.registry import build_adapter, decode_credentials

    cipher = _require_cipher()
    account = await _get_user_bank(session, user, bank_account_id)
    try:
        username, password = decode_credentials(account, cipher=cipher)
        adapter = build_adapter(
            bank_code=account.bank_code, username=username, password=password
        )
        await adapter.login()
    except BankAuthError as exc:
        account.verified_at = None
        account.polling_status = "auth_failed"
        account.last_error = f"{type(exc).__name__}: {exc}"
        await record_audit(
            session,
            actor=user.id,
            action="bank.verify_failed",
            target_type="bank_account",
            target_id=account.id,
            ip=request.client.host if request.client else None,
            after={"error": account.last_error},
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Đăng nhập thất bại: {exc}",
        ) from exc
    except BankRateLimited as exc:
        account.last_error = "rate_limited"
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Bank đang rate-limit; thử lại sau 60s.",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        account.verified_at = None
        account.last_error = f"{type(exc).__name__}: {exc}"[:500]
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Không kết nối được bank: {exc}",
        ) from exc

    now = datetime.now(UTC)
    account.verified_at = now
    account.last_login_at = now
    account.last_error = None
    account.polling_status = "running"
    await record_audit(
        session,
        actor=user.id,
        action="bank.verify_ok",
        target_type="bank_account",
        target_id=account.id,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    # Kick worker re-pickup (nếu trước đó đang ở auth_failed → running).
    try:
        from packages.infra_pubsub import publish

        await publish("bank:account:added", account.id)
    except Exception:  # noqa: BLE001, S110
        pass
    return BankAccountRead.model_validate(account, from_attributes=True)


@router.patch(
    "/bank-accounts/{bank_account_id}", response_model=BankAccountRead
)
async def update_bank_account(
    bank_account_id: str,
    payload: BankAccountUpdate,
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> BankAccountRead:
    """Pause/resume polling cho 1 bank account.

    Use case chính: user muốn dùng app mobile của ngân hàng (chuyển tiền,
    đổi mật khẩu) — bật `polling_enabled=false` để worker bỏ task poll, MB
    không kick session mobile. Khi xong, bật lại `true` và worker tự pickup
    qua kênh pubsub (best-effort) hoặc tick rescan kế tiếp.
    """
    account = await _get_user_bank(session, user, bank_account_id)
    if account.polling_enabled == payload.polling_enabled:
        # Idempotent: trả về luôn, không audit.
        return BankAccountRead.model_validate(account, from_attributes=True)

    account.polling_enabled = payload.polling_enabled
    if payload.polling_enabled:
        # Reset trạng thái lỗi cũ để worker khởi động sạch sẽ.
        account.last_error = None
        account.polling_status = "idle"
    await record_audit(
        session,
        actor=user.id,
        action="bank.resume" if payload.polling_enabled else "bank.pause",
        target_type="bank_account",
        target_id=account.id,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    # Báo worker rescan để cancel task cũ (pause) hoặc start task mới (resume).
    try:
        from packages.infra_pubsub import publish

        await publish("bank:account:added", account.id)
    except Exception:  # noqa: BLE001, S110
        pass
    return BankAccountRead.model_validate(account, from_attributes=True)


@router.post(
    "/bank-accounts/{bank_account_id}/rotate", response_model=BankAccountRead
)
async def rotate_bank_credentials(
    bank_account_id: str,
    payload: BankAccountRotate,
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> BankAccountRead:
    cipher = _require_cipher()
    account = await _get_user_bank(session, user, bank_account_id)
    account.credentials_enc = cipher.encrypt(f"{payload.username}:{payload.password}")
    account.last_error = None
    account.verified_at = None
    await record_audit(
        session,
        actor=user.id,
        action="bank.rotate",
        target_type="bank_account",
        target_id=account.id,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    # Kick worker để re-login với credential mới ngay.
    try:
        from packages.infra_pubsub import publish

        await publish("bank:account:added", account.id)
    except Exception:  # noqa: BLE001, S110
        pass
    return BankAccountRead.model_validate(account, from_attributes=True)


@router.delete(
    "/bank-accounts/{bank_account_id}", response_model=GenericMessage
)
async def delete_bank_account(
    bank_account_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    account = await _get_user_bank(session, user, bank_account_id)
    # Không cho xoá nếu còn order pending
    pending = await session.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.bank_account_id == account.id)
        .where(Order.status == "pending")
    )
    if int(pending or 0) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="cannot delete bank account with pending orders",
        )
    account.status = "deleted"
    account.polling_enabled = False
    await record_audit(
        session,
        actor=user.id,
        action="bank.delete",
        target_type="bank_account",
        target_id=account.id,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    # Kick worker để cancel poll task của bank vừa xoá.
    try:
        from packages.infra_pubsub import publish

        await publish("bank:account:added", account.id)
    except Exception:  # noqa: BLE001, S110
        pass
    return GenericMessage(message="deleted")


async def _get_user_bank(
    session: AsyncSession, user: User, bank_id: str
) -> BankAccount:
    account = await session.get(BankAccount, bank_id)
    if account is None or account.user_id != user.id or account.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return account


# ---------------------------------------------------------------------------
# WEBHOOKS
# ---------------------------------------------------------------------------


@router.get("/webhooks", response_model=list[MeWebhookRead])
async def list_webhooks(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[MeWebhookRead]:
    rows = list(
        (
            await session.scalars(
                select(Webhook)
                .where(Webhook.user_id == user.id)
                .order_by(Webhook.created_at.desc())
            )
        ).all()
    )
    return [MeWebhookRead.model_validate(r, from_attributes=True) for r in rows]


@router.post("/webhooks", response_model=MeWebhookRead, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    payload: MeWebhookCreate,
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> MeWebhookRead:
    try:
        validate_webhook_url(str(payload.url))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    try:
        secret_value = encrypt_webhook_secret(payload.secret)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    webhook = Webhook(
        user_id=user.id,
        owner_id=user.id,
        name=payload.name,
        url=str(payload.url),
        secret_enc=secret_value,
        active=payload.active,
        headers_json=dict(payload.headers),
        events_json={"events": list(payload.events)},
    )
    session.add(webhook)
    await session.flush()
    await record_audit(
        session,
        actor=user.id,
        action="webhook.create",
        target_type="webhook",
        target_id=webhook.id,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return MeWebhookRead.model_validate(webhook, from_attributes=True)


@router.patch("/webhooks/{webhook_id}", response_model=MeWebhookRead)
async def update_webhook(
    webhook_id: str,
    payload: MeWebhookUpdate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> MeWebhookRead:
    webhook = await _get_user_webhook(session, user, webhook_id)
    if payload.name is not None:
        webhook.name = payload.name or None
    if payload.active is not None:
        webhook.active = payload.active
    if payload.events is not None:
        webhook.events_json = {"events": list(payload.events)}
    await session.commit()
    return MeWebhookRead.model_validate(webhook, from_attributes=True)


@router.delete("/webhooks/{webhook_id}", response_model=GenericMessage)
async def delete_webhook(
    webhook_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    webhook = await _get_user_webhook(session, user, webhook_id)
    await session.delete(webhook)
    await session.commit()
    return GenericMessage(message="deleted")


@router.get("/webhooks/{webhook_id}/attempts", response_model=list[dict[str, Any]])
async def webhook_attempts(
    webhook_id: str,
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    await _get_user_webhook(session, user, webhook_id)
    rows = list(
        (
            await session.scalars(
                select(WebhookAttempt)
                .where(WebhookAttempt.webhook_id == webhook_id)
                .order_by(desc(WebhookAttempt.next_run_at))
                .limit(limit)
            )
        ).all()
    )
    return [
        {
            "id": r.id,
            "status": r.status,
            "attempt": r.attempt,
            "next_run_at": r.next_run_at.isoformat() if r.next_run_at else None,
            "last_status_code": r.last_status_code,
            "last_error": r.last_error,
            "sent_at": r.sent_at.isoformat() if r.sent_at else None,
        }
        for r in rows
    ]


@router.post("/webhooks/{webhook_id}/attempts/{attempt_id}/replay", response_model=GenericMessage)
async def replay_attempt(
    webhook_id: str,
    attempt_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    await _get_user_webhook(session, user, webhook_id)
    attempt = await session.get(WebhookAttempt, attempt_id)
    if attempt is None or attempt.webhook_id != webhook_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    attempt.status = "pending"
    attempt.next_run_at = utcnow()
    attempt.last_error = None
    await session.commit()
    return GenericMessage(message="queued")


@router.post("/webhooks/{webhook_id}/test")
async def send_test_ping(
    webhook_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Gửi 1 webhook test inline (event "webhook.test") và trả ngay kết quả.

    KHÔNG ghi vào `webhook_attempts` (vì cột order_id/transaction_id là FK
    non-null, không khớp với event test). Đường gửi dùng cùng logic ký HMAC +
    SSRF guard như dispatcher để nội dung header `X-Signature` giống production.
    """
    import json as _json

    import httpx as _httpx

    from packages.webhook import decrypt_webhook_secret, is_safe_webhook_url
    from packages.webhook.signing import sign_payload as _sign

    webhook = await _get_user_webhook(session, user, webhook_id)

    ok_url, reason = is_safe_webhook_url(webhook.url)
    if not ok_url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"URL không an toàn: {reason}",
        )

    secret_plain = decrypt_webhook_secret(webhook.secret_enc)
    payload = {
        "id": f"evt_test_{secrets.token_hex(8)}",
        "type": "webhook.test",
        "created_at": datetime.now(UTC).isoformat(),
        "data": {
            "message": "Đây là webhook test từ APIBank.",
            "user_id": user.id,
        },
    }
    body = _json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    timestamp = int(datetime.now(UTC).timestamp())
    signature = _sign(secret=secret_plain, body=body, timestamp=timestamp)

    status_code: int | None = None
    error: str | None = None
    try:
        async with _httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                webhook.url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Signature": signature,
                    **(webhook.headers_json or {}),
                },
                follow_redirects=False,
            )
        status_code = response.status_code
    except Exception as exc:  # noqa: BLE001
        error = repr(exc)

    await record_audit(
        session,
        actor=user.id,
        action="webhook.test",
        target_type="webhook",
        target_id=webhook.id,
        after={"status_code": status_code, "error": error},
    )
    await session.commit()
    delivered = status_code is not None and 200 <= status_code < 300
    return {
        "delivered": delivered,
        "status_code": status_code,
        "error": error,
        "signature": signature,
        "event_id": payload["id"],
    }


async def _get_user_webhook(
    session: AsyncSession, user: User, webhook_id: str
) -> Webhook:
    webhook = await session.get(Webhook, webhook_id)
    if webhook is None or webhook.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return webhook


# ---------------------------------------------------------------------------
# API KEYS
# ---------------------------------------------------------------------------


_ALLOWED_SCOPES = {
    "orders:read",
    "orders:write",
    "transactions:read",
    "webhooks:read",
}


@router.get("/api-keys", response_model=list[MeApiKeyRead])
async def list_api_keys(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[MeApiKeyRead]:
    rows = list(
        (
            await session.scalars(
                select(ApiKey)
                .where(ApiKey.user_id == user.id)
                .order_by(ApiKey.created_at.desc())
            )
        ).all()
    )
    return [MeApiKeyRead.model_validate(r, from_attributes=True) for r in rows]


@router.post("/api-keys", response_model=MeApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key_for_user(
    payload: MeApiKeyCreate,
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> MeApiKeyCreated:
    invalid = [s for s in payload.scopes if s not in _ALLOWED_SCOPES]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid scopes: {invalid}",
        )
    raw = generate_api_key()
    digest = hash_api_key(raw, salt=get_settings().api_key_salt)
    record = ApiKey(
        owner_id=user.id,
        user_id=user.id,
        name=payload.name,
        key_hash=digest,
        scopes=list(payload.scopes),
        expires_at=payload.expires_at,
    )
    session.add(record)
    await session.flush()
    await record_audit(
        session,
        actor=user.id,
        action="apikey.create",
        target_type="api_key",
        target_id=record.id,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    payload_out = MeApiKeyRead.model_validate(record, from_attributes=True).model_dump()
    return MeApiKeyCreated(**payload_out, raw_key=raw)


@router.post("/api-keys/{api_key_id}/revoke", response_model=GenericMessage)
async def revoke_api_key(
    api_key_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    record = await session.get(ApiKey, api_key_id)
    if record is None or record.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    if record.revoked_at is None:
        record.revoked_at = datetime.now(UTC)
        await session.commit()
    return GenericMessage(message="revoked")


# ---------------------------------------------------------------------------
# WALLET + TOPUP
# ---------------------------------------------------------------------------


@router.get("/wallet", response_model=WalletBalanceRead)
async def get_wallet(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> WalletBalanceRead:
    # Đếm pending topups dùng cột Order.user_id đã denormalize (kèm index).
    # Fallback OR-clause với customer_ref để tương thích các topup cũ tạo
    # trước khi backfill chạy xong.
    pending = await session.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.status == "pending")
        .where(
            (Order.user_id == user.id) | (Order.customer_ref == user.email)
        )
    )
    return WalletBalanceRead(
        balance_vnd=Decimal(user.balance_vnd),
        pending_topups=int(pending or 0),
    )


@router.get("/wallet/transactions", response_model=list[WalletTransactionRead])
async def list_wallet_transactions(
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[WalletTransactionRead]:
    rows = await wallet_pkg.list_transactions(session, user_id=user.id, limit=limit)
    return [WalletTransactionRead.model_validate(r, from_attributes=True) for r in rows]


@router.post("/topup", response_model=TopupResponse, status_code=status.HTTP_201_CREATED)
async def create_topup(
    payload: TopupCreateRequest,
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> TopupResponse:
    try:
        order = await topup_pkg.create_topup_order(
            session, user=user, amount_vnd=payload.amount_vnd
        )
    except SystemBankNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    await record_audit(
        session,
        actor=user.id,
        action="topup.create",
        target_type="order",
        target_id=order.id,
        ip=request.client.host if request.client else None,
        after={"amount_vnd": int(order.amount_vnd)},
    )
    bank = await session.get(BankAccount, order.bank_account_id)
    await session.commit()
    # qr_url: dùng URL ảnh từ VietQR (img.vietqr.io) — chuẩn QRIBFTTA, app
    # banking VN scan ổn định hơn payload TLV tự sinh. CSP đã whitelist domain
    # này. pay_url đường dẫn tương đối để tránh mixed-content sau tunnel/CDN.
    bank_code = bank.bank_code if bank else ""
    bank_name = _BANK_NAME.get(bank_code.upper(), bank_code) if bank else ""
    qr_url = (
        vietqr_image_url(
            bank_code=bank_code,
            account_no=bank.account_no,
            amount_vnd=int(order.amount_vnd),
            content=order.code,
            account_holder=bank.account_holder,
        )
        if bank
        else ""
    )
    return TopupResponse(
        order_id=order.id,
        code=order.code,
        amount_vnd=Decimal(order.amount_vnd),
        status=order.status,
        expired_at=order.expired_at,
        pay_url=f"/pay/{order.code}",
        qr_url=qr_url,
        bank_code=bank_code,
        bank_name=bank_name,
        account_no=bank.account_no if bank else "",
        account_holder=bank.account_holder if bank else "",
        transfer_content=order.code,
    )


def _topup_list_item(order: Order, bank: BankAccount | None) -> TopupListItem:
    bank_code = bank.bank_code if bank else ""
    bank_name = _BANK_NAME.get(bank_code.upper(), bank_code) if bank else ""
    qr_url = (
        vietqr_image_url(
            bank_code=bank_code,
            account_no=bank.account_no,
            amount_vnd=int(order.amount_vnd),
            content=order.code,
            account_holder=bank.account_holder,
        )
        if bank
        else ""
    )
    return TopupListItem(
        order_id=order.id,
        code=order.code,
        amount_vnd=Decimal(order.amount_vnd),
        status=order.status,
        created_at=order.created_at,
        expired_at=order.expired_at,
        pay_url=f"/pay/{order.code}",
        qr_url=qr_url,
        bank_code=bank_code,
        bank_name=bank_name,
        account_no=bank.account_no if bank else "",
        account_holder=bank.account_holder if bank else "",
        transfer_content=order.code,
    )


@router.get("/topups", response_model=list[TopupListItem])
async def list_pending_topups(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[TopupListItem]:
    """Liệt kê đơn nạp ví đang `pending` của user — để khôi phục lại QR khi
    user lỡ đóng dialog hoặc reload trang."""
    rows = list(
        (
            await session.scalars(
                select(Order)
                .where(Order.status == "pending")
                .where(
                    (Order.user_id == user.id)
                    | (Order.customer_ref == user.email)
                )
                .order_by(desc(Order.created_at))
                .limit(20)
            )
        ).all()
    )
    if not rows:
        return []
    bank_ids = {o.bank_account_id for o in rows}
    banks_result = await session.scalars(
        select(BankAccount).where(BankAccount.id.in_(bank_ids))
    )
    banks = {b.id: b for b in banks_result.all()}
    out: list[TopupListItem] = []
    for order in rows:
        # chỉ trả các order thực sự là topup (loại trừ order thường nếu trùng email)
        meta = order.metadata_json or {}
        if meta.get("kind") != topup_pkg.TOPUP_KIND:
            continue
        if meta.get("user_id") and meta.get("user_id") != user.id:
            continue
        out.append(_topup_list_item(order, banks.get(order.bank_account_id)))
    return out


@router.post("/topups/{order_id}:cancel", response_model=TopupListItem)
async def cancel_pending_topup(
    order_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> TopupListItem:
    """User chủ động huỷ đơn nạp đang chờ.

    Bảo vệ:
    - Chỉ owner (theo metadata.user_id hoặc customer_ref==email).
    - Chỉ huỷ được khi status còn `pending`.
    """
    order = await session.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="topup not found")
    meta = order.metadata_json or {}
    if meta.get("kind") != topup_pkg.TOPUP_KIND:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="topup not found")
    is_owner = meta.get("user_id") == user.id or order.customer_ref == user.email
    if not is_owner:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="topup not found")
    if order.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"cannot cancel topup in status '{order.status}'",
        )
    order.status = "canceled"
    order.updated_at = datetime.now(UTC)
    bank = await session.get(BankAccount, order.bank_account_id)
    await record_audit(
        session,
        actor=user.id,
        action="topup.cancel",
        target_type="order",
        target_id=order.id,
        ip=request.client.host if request.client else None,
        before={"status": "pending"},
        after={"status": "canceled"},
    )
    await session.commit()
    return _topup_list_item(order, bank)


# Tổng thời gian backend đợi trạng thái mới sau khi kick worker. Worker poll
# bank ~20s/lần, nên 12s bao quát phần lớn case "vừa CK xong vài giây trước".
# Vượt quá → trả pending; FE hiển thị toast "đang chờ", user có thể bấm lại.
_TOPUP_CHECK_MAX_WAIT_SEC = 12.0
_TOPUP_CHECK_POLL_SEC = 0.5


@router.post("/topups/{order_id}:check", response_model=TopupCheckResponse)
async def check_pending_topup(
    order_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> TopupCheckResponse:
    """User bấm "Tôi đã chuyển khoản" — kick worker poll ngay rồi đợi check.

    Flow:
      1. Verify order tồn tại + thuộc về user + là topup.
      2. Nếu đã ``paid`` → trả ngay với balance hiện tại.
      3. Nếu ``pending`` → ``poll_kick.kick(bank_id)`` để worker thoát sleep
         poll_interval, fetch tx mới ngay. BE poll DB mỗi 0.5s, đợi tối đa
         12s xem order có chuyển ``paid`` không.
      4. Hết thời gian vẫn ``pending`` → trả ``pending`` + message hướng dẫn.

    Idempotent: gọi nhiều lần an toàn (chỉ kick poll loop, không tạo order/tx).
    Audit: ghi action ``topup.check`` để admin trace user lạm dụng.
    """
    order = await session.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="topup not found")
    meta = order.metadata_json or {}
    if meta.get("kind") != topup_pkg.TOPUP_KIND:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="topup not found")
    is_owner = meta.get("user_id") == user.id or order.customer_ref == user.email
    if not is_owner:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="topup not found")

    initial_status = order.status

    # Đã paid trước đó → trả luôn balance, không cần kick.
    if initial_status == "paid":
        return TopupCheckResponse(
            order_id=order.id,
            code=order.code,
            status="paid",
            balance_vnd=Decimal(user.balance_vnd),
            waited_ms=0,
            message="Đơn nạp đã được ghi nhận. Số dư đã cộng vào ví.",
        )

    if initial_status in ("expired", "canceled"):
        return TopupCheckResponse(
            order_id=order.id,
            code=order.code,
            status=initial_status,
            waited_ms=0,
            message=(
                "Đơn nạp đã hết hạn." if initial_status == "expired"
                else "Đơn nạp đã bị huỷ."
            ),
        )

    # Audit user click — phòng abuse + trace khi user kêu "tiền không về".
    await record_audit(
        session,
        actor=user.id,
        action="topup.check",
        target_type="order",
        target_id=order.id,
        ip=request.client.host if request.client else None,
        after={"amount_vnd": int(order.amount_vnd)},
    )
    await session.commit()

    # Kick worker poll loop. Best-effort — nếu cả Redis lẫn local đều
    # không có subscriber (vd worker chưa chạy), vẫn fallback poll DB,
    # nhưng có thể không thấy tx mới trong 12s.
    await poll_kick.kick(order.bank_account_id)

    loop = asyncio.get_running_loop()
    started = loop.time()
    while True:
        await asyncio.sleep(_TOPUP_CHECK_POLL_SEC)
        # Re-fetch order ở session mới để tránh đọc bản cache đã expunged.
        await session.refresh(order)
        if order.status == "paid":
            await session.refresh(user)
            elapsed_ms = int((loop.time() - started) * 1000)
            return TopupCheckResponse(
                order_id=order.id,
                code=order.code,
                status="paid",
                balance_vnd=Decimal(user.balance_vnd),
                waited_ms=elapsed_ms,
                message="Nạp tiền thành công, số dư đã được cộng.",
            )
        if order.status in ("expired", "canceled"):
            elapsed_ms = int((loop.time() - started) * 1000)
            return TopupCheckResponse(
                order_id=order.id,
                code=order.code,
                status=order.status,
                waited_ms=elapsed_ms,
                message=(
                    "Đơn nạp đã hết hạn trong lúc check."
                    if order.status == "expired"
                    else "Đơn nạp đã bị huỷ."
                ),
            )
        if loop.time() - started >= _TOPUP_CHECK_MAX_WAIT_SEC:
            elapsed_ms = int((loop.time() - started) * 1000)
            return TopupCheckResponse(
                order_id=order.id,
                code=order.code,
                status="pending",
                waited_ms=elapsed_ms,
                message=(
                    "Hệ thống chưa thấy giao dịch. Nếu bạn vừa chuyển khoản, "
                    "vui lòng đợi 30–60 giây để ngân hàng cập nhật rồi thử lại."
                ),
            )


# ---------------------------------------------------------------------------
# PLANS / SUBSCRIPTION / INVOICES
# ---------------------------------------------------------------------------


@public_router.get("/plans", response_model=list[PlanRead])
async def list_plans(
    session: AsyncSession = Depends(get_session),
) -> list[PlanRead]:
    rows = list(
        (
            await session.scalars(
                select(Plan)
                .where(Plan.active.is_(True))
                .order_by(Plan.sort_order, Plan.price_vnd)
            )
        ).all()
    )
    return [PlanRead.model_validate(r, from_attributes=True) for r in rows]


@router.get("/subscription", response_model=SubscriptionRead | None)
async def my_subscription(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> SubscriptionRead | None:
    sub = await subscription_pkg.get_active_subscription(session, user.id)
    if sub is None:
        return None
    plan = await session.get(Plan, sub.plan_id)
    payload = SubscriptionRead.model_validate(sub, from_attributes=True)
    payload.plan_code = plan.code if plan else None
    return payload


@router.post("/subscription/purchase", response_model=SubscriptionRead)
async def purchase_subscription(
    payload: SubscriptionPurchaseRequest,
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> SubscriptionRead:
    try:
        sub, _invoice = await subscription_pkg.purchase(
            session,
            user=user,
            plan_code=payload.plan_code,
            idempotency_key=f"sub:{user.id}:{payload.plan_code}:{secrets.token_hex(8)}",
        )
    except PlanNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InsufficientFundsError as exc:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc)) from exc
    await record_audit(
        session,
        actor=user.id,
        action="subscription.purchase",
        target_type="subscription",
        target_id=sub.id,
        ip=request.client.host if request.client else None,
        after={"plan_code": payload.plan_code},
    )
    await session.commit()
    out = SubscriptionRead.model_validate(sub, from_attributes=True)
    out.plan_code = payload.plan_code
    return out


@router.get("/invoices", response_model=list[InvoiceRead])
async def my_invoices(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[InvoiceRead]:
    rows = list(
        (
            await session.scalars(
                select(Invoice)
                .where(Invoice.user_id == user.id)
                .order_by(Invoice.issued_at.desc())
            )
        ).all()
    )
    return [InvoiceRead.model_validate(r, from_attributes=True) for r in rows]


# ---------------------------------------------------------------------------
# ORDERS / TRANSACTIONS list
# ---------------------------------------------------------------------------


@router.get("/orders", response_model=list[OrderListItem])
async def list_my_orders(
    status_filter: str | None = Query(default=None, alias="status"),
    bank_account_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[OrderListItem]:
    user_bank_ids = list(
        (
            await session.scalars(
                select(BankAccount.id).where(BankAccount.user_id == user.id)
            )
        ).all()
    )
    if not user_bank_ids:
        return []
    stmt = (
        select(Order)
        .where(Order.bank_account_id.in_(user_bank_ids))
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    if status_filter:
        stmt = stmt.where(Order.status == status_filter)
    if bank_account_id:
        stmt = stmt.where(Order.bank_account_id == bank_account_id)
    rows = list((await session.scalars(stmt)).all())
    return [OrderListItem.model_validate(r, from_attributes=True) for r in rows]


@router.get("/transactions", response_model=list[TransactionListItem])
async def list_my_transactions(
    state: str | None = None,
    bank_account_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[TransactionListItem]:
    user_bank_ids = list(
        (
            await session.scalars(
                select(BankAccount.id).where(BankAccount.user_id == user.id)
            )
        ).all()
    )
    if not user_bank_ids:
        return []
    stmt = (
        select(Transaction)
        .where(Transaction.bank_account_id.in_(user_bank_ids))
        .order_by(Transaction.posted_at.desc())
        .limit(limit)
    )
    if state:
        stmt = stmt.where(Transaction.state == state)
    if bank_account_id:
        stmt = stmt.where(Transaction.bank_account_id == bank_account_id)
    rows = list((await session.scalars(stmt)).all())
    return [TransactionListItem.model_validate(r, from_attributes=True) for r in rows]


# ---------------------------------------------------------------------------
# NOTIFICATIONS (in-app inbox)
# ---------------------------------------------------------------------------


@router.get("/notifications", response_model=list[NotificationRead])
async def list_notifications(
    limit: int = Query(20, ge=1, le=100),
    unread_only: bool = False,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[NotificationRead]:
    stmt = (
        select(Notification)
        .where(Notification.user_id == user.id)
        .where(Notification.channel == "in_app")
        .order_by(desc(Notification.created_at))
        .limit(limit)
    )
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    rows = list((await session.scalars(stmt)).all())
    return [NotificationRead.model_validate(r, from_attributes=True) for r in rows]


@router.get("/notifications/unread-count", response_model=NotificationUnreadCount)
async def notifications_unread_count(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> NotificationUnreadCount:
    count = await session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user.id)
        .where(Notification.channel == "in_app")
        .where(Notification.read_at.is_(None))
    )
    return NotificationUnreadCount(unread=int(count or 0))


@router.patch("/notifications/{notification_id}", response_model=NotificationRead)
async def mark_notification_read(
    notification_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> NotificationRead:
    record = await session.get(Notification, notification_id)
    if record is None or record.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    if record.read_at is None:
        record.read_at = datetime.now(UTC)
        await session.commit()
    return NotificationRead.model_validate(record, from_attributes=True)


@router.post("/notifications/read-all", response_model=GenericMessage)
async def mark_all_notifications_read(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    from sqlalchemy import update

    now = datetime.now(UTC)
    await session.execute(
        update(Notification)
        .where(Notification.user_id == user.id)
        .where(Notification.channel == "in_app")
        .where(Notification.read_at.is_(None))
        .values(read_at=now)
    )
    await session.commit()
    return GenericMessage(message="ok")


# ---------------------------------------------------------------------------
# NOTIFICATION PREFERENCES (matrix kind x channel)
# ---------------------------------------------------------------------------


@router.get("/notification-preferences", response_model=NotificationPreferenceList)
async def list_notification_preferences(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> NotificationPreferenceList:
    """Trả về toàn bộ matrix prefs (kind x channel).

    Hợp nhất default channels (xem `packages.notifications.dispatcher.DEFAULT_CHANNELS`)
    với prefs đã ghi DB. Nếu user chưa override → enabled = (channel có trong default
    của kind đó).
    """
    from packages.notifications.dispatcher import DEFAULT_CHANNELS

    rows = list(
        (
            await session.scalars(
                select(NotificationPreference).where(
                    NotificationPreference.user_id == user.id
                )
            )
        ).all()
    )
    overrides: dict[tuple[str, str], bool] = {
        (r.kind, r.channel): r.enabled for r in rows
    }

    items: list[NotificationPreferenceItem] = []
    for kind, default_channels in DEFAULT_CHANNELS.items():
        for channel in VALID_NOTIFICATION_CHANNELS:
            key = (kind, channel)
            enabled = overrides.get(key, channel in default_channels)
            items.append(
                NotificationPreferenceItem(kind=kind, channel=channel, enabled=enabled)
            )
    return NotificationPreferenceList(items=items)


@router.put("/notification-preferences", response_model=NotificationPreferenceList)
async def update_notification_preferences(
    payload: NotificationPreferenceUpdate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> NotificationPreferenceList:
    """Bulk upsert prefs. Mỗi item ghi đè cặp (user, kind, channel)."""
    from packages.notifications.dispatcher import DEFAULT_CHANNELS

    valid_kinds = set(DEFAULT_CHANNELS.keys())
    for it in payload.items:
        if it.kind not in valid_kinds:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"unknown kind: {it.kind}",
            )
        if it.channel not in VALID_NOTIFICATION_CHANNELS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"unknown channel: {it.channel}",
            )

    # Load existing rows một lần để tránh N+1.
    existing = list(
        (
            await session.scalars(
                select(NotificationPreference).where(
                    NotificationPreference.user_id == user.id
                )
            )
        ).all()
    )
    by_key: dict[tuple[str, str], NotificationPreference] = {
        (r.kind, r.channel): r for r in existing
    }

    for it in payload.items:
        key = (it.kind, it.channel)
        row = by_key.get(key)
        if row is None:
            row = NotificationPreference(
                user_id=user.id,
                kind=it.kind,
                channel=it.channel,
                enabled=it.enabled,
            )
            session.add(row)
            by_key[key] = row
        else:
            row.enabled = it.enabled

    await session.commit()
    return await list_notification_preferences(user=user, session=session)
