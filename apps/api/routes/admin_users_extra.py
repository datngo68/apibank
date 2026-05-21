"""Admin user lifecycle — bulk, impersonate, sessions, lock, GDPR.

Phase 3 — Users CRITICAL extensions. Mọi mutation đều audit; impersonate
có TTL ngắn (30 phút) và audit kỹ.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from packages.config.settings import get_settings
from packages.db.models import (
    ApiKey,
    AuditLog,
    BankAccount,
    User,
    UserNote,
    UserTag,
    Webhook,
)
from packages.db.models import (
    Session as SessionModel,
)
from packages.db.session import get_session
from packages.schemas.auth import GenericMessage
from packages.security.audit import record_audit
from packages.security.sessions import (
    issue_session,
    revoke_all_sessions,
    revoke_session,
)
from packages.security.user_auth import current_admin_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/admin", tags=["admin-users-extra"])

COOKIE_NAME = "apibank_session"


# ---------------------------------------------------------------------------
# BULK ACTIONS
# ---------------------------------------------------------------------------


@router.post("/users/bulk", response_model=GenericMessage)
async def admin_bulk_user_action(
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
    action: str = Query(..., pattern="^(suspend|activate|delete)$"),
    ids: list[str] = Query(..., description="Danh sách user_id"),
) -> GenericMessage:
    if not ids:
        raise HTTPException(status_code=400, detail="ids rỗng")
    if actor.id in ids:
        raise HTTPException(status_code=400, detail="không tự apply cho chính mình")
    target_status = {
        "suspend": "suspended",
        "activate": "active",
        "delete": "deleted",
    }[action]
    values: dict[str, Any] = {"status": target_status}
    if action == "delete":
        values["deleted_at"] = datetime.now(UTC)
    result = await session.execute(
        update(User).where(User.id.in_(ids)).values(**values)
    )
    affected = getattr(result, "rowcount", len(ids)) or 0
    await record_audit(
        session,
        actor=actor.id,
        action=f"admin.user.bulk_{action}",
        target_type="user",
        target_id="*",
        ip=request.client.host if request.client else None,
        after={"ids": ids, "affected": affected},
    )
    await session.commit()
    return GenericMessage(message=f"{action} {affected} users")


# ---------------------------------------------------------------------------
# IMPERSONATE
# ---------------------------------------------------------------------------


_IMPERSONATE_TTL_SECONDS = 30 * 60


@router.post("/users/{user_id}:impersonate", response_model=GenericMessage)
async def admin_impersonate(
    user_id: str,
    request: Request,
    response: Response,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    """Cấp session ngắn (30 phút) cho admin login-as user.

    Audit kỹ: trước/sau, IP, UA. Cookie `apibank_session` set như login bình
    thường — KHÔNG đụng đến cookie admin (`apibank_admin`). Để thoát, admin
    revoke session qua /auth/logout-all hoặc tự logout trên FE.
    """
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    if target.status != "active":
        raise HTTPException(status_code=400, detail="user inactive")
    raw, _record = await issue_session(
        session,
        target,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        ttl=timedelta(seconds=_IMPERSONATE_TTL_SECONDS),
    )
    secure = get_settings().cookie_secure_effective
    response.set_cookie(
        COOKIE_NAME,
        raw,
        max_age=_IMPERSONATE_TTL_SECONDS,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    await record_audit(
        session,
        actor=actor.id,
        action="admin.user.impersonate",
        target_type="user",
        target_id=target.id,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        after={"ttl": _IMPERSONATE_TTL_SECONDS, "target_email": target.email},
    )
    await session.commit()
    return GenericMessage(message=f"impersonating {target.email}")


# ---------------------------------------------------------------------------
# SESSIONS
# ---------------------------------------------------------------------------


@router.get("/users/{user_id}/sessions")
async def admin_list_user_sessions(
    user_id: str,
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    rows = list(
        (
            await session.scalars(
                select(SessionModel)
                .where(SessionModel.user_id == user_id)
                .where(SessionModel.revoked_at.is_(None))
                .order_by(desc(SessionModel.last_seen_at))
            )
        ).all()
    )
    return [
        {
            "id": s.id,
            "ip": s.ip,
            "user_agent": s.user_agent,
            "created_at": s.created_at.isoformat(),
            "last_seen_at": s.last_seen_at.isoformat(),
            "expires_at": s.expires_at.isoformat(),
        }
        for s in rows
    ]


@router.delete("/users/{user_id}/sessions/{session_id}", response_model=GenericMessage)
async def admin_revoke_session(
    user_id: str,
    session_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    target_sess = await session.get(SessionModel, session_id)
    if target_sess is None or target_sess.user_id != user_id:
        raise HTTPException(status_code=404, detail="session not found")
    await revoke_session(session, session_id)
    await record_audit(
        session,
        actor=actor.id,
        action="admin.user.session.revoke",
        target_type="session",
        target_id=session_id,
        ip=request.client.host if request.client else None,
        after={"target_user": user_id},
    )
    await session.commit()
    return GenericMessage(message="revoked")


@router.post("/users/{user_id}/sessions:revoke-all", response_model=GenericMessage)
async def admin_revoke_all_sessions(
    user_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    await revoke_all_sessions(session, user_id)
    await record_audit(
        session,
        actor=actor.id,
        action="admin.user.session.revoke_all",
        target_type="user",
        target_id=user_id,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return GenericMessage(message="all sessions revoked")


# ---------------------------------------------------------------------------
# VERIFY EMAIL / LOCK / UNLOCK
# ---------------------------------------------------------------------------


@router.post("/users/{user_id}:verify-email", response_model=GenericMessage)
async def admin_verify_email(
    user_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="not found")
    target.email_verified_at = datetime.now(UTC)
    await record_audit(
        session,
        actor=actor.id,
        action="admin.user.verify_email",
        target_type="user",
        target_id=user_id,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return GenericMessage(message="verified")


@router.post("/users/{user_id}:lock", response_model=GenericMessage)
async def admin_lock_user(
    user_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
    minutes: int = Query(default=60, ge=1, le=10_080),
) -> GenericMessage:
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="not found")
    target.locked_until = datetime.now(UTC) + timedelta(minutes=minutes)
    await record_audit(
        session,
        actor=actor.id,
        action="admin.user.lock",
        target_type="user",
        target_id=user_id,
        ip=request.client.host if request.client else None,
        after={"minutes": minutes},
    )
    await session.commit()
    return GenericMessage(message=f"locked until {target.locked_until.isoformat()}")


@router.post("/users/{user_id}:unlock", response_model=GenericMessage)
async def admin_unlock_user(
    user_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="not found")
    target.locked_until = None
    target.failed_login_count = 0
    await record_audit(
        session,
        actor=actor.id,
        action="admin.user.unlock",
        target_type="user",
        target_id=user_id,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return GenericMessage(message="unlocked")


# ---------------------------------------------------------------------------
# GDPR DELETE / ANONYMIZE
# ---------------------------------------------------------------------------


@router.delete("/users/{user_id}", response_model=GenericMessage)
async def admin_soft_delete_user(
    user_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="not found")
    if target.id == actor.id:
        raise HTTPException(status_code=400, detail="không tự xoá")
    target.status = "deleted"
    target.deleted_at = datetime.now(UTC)
    # Revoke session, revoke api keys, tắt webhook + bank polling.
    await revoke_all_sessions(session, user_id)
    await session.execute(
        update(ApiKey)
        .where(ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await session.execute(
        update(Webhook).where(Webhook.user_id == user_id).values(active=False)
    )
    await session.execute(
        update(BankAccount)
        .where(BankAccount.user_id == user_id)
        .values(polling_enabled=False, status="deleted")
    )
    await record_audit(
        session,
        actor=actor.id,
        action="admin.user.delete",
        target_type="user",
        target_id=user_id,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return GenericMessage(message="deleted")


@router.post("/users/{user_id}:anonymize", response_model=GenericMessage)
async def admin_anonymize_user(
    user_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    """Right-to-be-forgotten: hash email/full_name/ip còn giữ ledger.

    Các field quan trọng cho audit (id, balance, transaction) giữ nguyên;
    PII bị thay placeholder kiểu ``deleted-<short_hash>@example.invalid``.
    """
    import hashlib

    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="not found")
    if target.id == actor.id:
        raise HTTPException(status_code=400, detail="không tự anonymize")

    digest = hashlib.sha256(target.email.encode()).hexdigest()[:12]
    placeholder = f"deleted-{digest}@example.invalid"
    target.email = placeholder
    target.full_name = None
    target.telegram_chat_id = None
    target.password_hash = "!"  # noqa: S105 — sentinel, không thể dùng để verify
    target.status = "deleted"
    target.deleted_at = datetime.now(UTC)
    await revoke_all_sessions(session, user_id)
    # Anonymize audit_log.ip cho rows mà actor là user này.
    await session.execute(
        update(AuditLog).where(AuditLog.actor == user_id).values(ip=None)
    )
    await record_audit(
        session,
        actor=actor.id,
        action="admin.user.anonymize",
        target_type="user",
        target_id=user_id,
        ip=request.client.host if request.client else None,
        after={"placeholder": placeholder},
    )
    await session.commit()
    return GenericMessage(message="anonymized")


# Export users CSV
@router.get("/users/export.csv")
async def admin_users_export_csv(
    role: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    import csv
    import io
    from collections.abc import AsyncIterator

    from fastapi.responses import StreamingResponse

    stmt = select(User)
    if role:
        stmt = stmt.where(User.role == role)
    if status_filter:
        stmt = stmt.where(User.status == status_filter)

    async def _gen() -> AsyncIterator[bytes]:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "id",
                "email",
                "full_name",
                "role",
                "status",
                "balance_vnd",
                "created_at",
                "last_login_at",
            ]
        )
        yield buf.getvalue().encode("utf-8")
        buf.seek(0)
        buf.truncate(0)
        rows = list((await session.scalars(stmt)).all())
        for u in rows:
            writer.writerow(
                [
                    u.id,
                    u.email,
                    u.full_name or "",
                    u.role,
                    u.status,
                    int(u.balance_vnd),
                    u.created_at.isoformat(),
                    u.last_login_at.isoformat() if u.last_login_at else "",
                ]
            )
            yield buf.getvalue().encode("utf-8")
            buf.seek(0)
            buf.truncate(0)

    return StreamingResponse(
        _gen(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=users.csv"},
    )


# ---------------------------------------------------------------------------
# USER NOTES & TAGS
# ---------------------------------------------------------------------------


@router.get("/users/{user_id}/notes")
async def admin_list_notes(
    user_id: str,
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    rows = list(
        (
            await session.scalars(
                select(UserNote)
                .where(UserNote.user_id == user_id)
                .order_by(desc(UserNote.created_at))
            )
        ).all()
    )
    return [
        {
            "id": n.id,
            "body": n.body,
            "created_by": n.created_by,
            "created_at": n.created_at.isoformat(),
        }
        for n in rows
    ]


@router.post("/users/{user_id}/notes", response_model=GenericMessage)
async def admin_add_note(
    user_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
    body: str = Query(..., min_length=1, max_length=5000),
) -> GenericMessage:
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    note = UserNote(user_id=user_id, body=body, created_by=actor.id)
    session.add(note)
    await record_audit(
        session,
        actor=actor.id,
        action="admin.user.note.add",
        target_type="user",
        target_id=user_id,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return GenericMessage(message="added")


@router.delete("/users/{user_id}/notes/{note_id}", response_model=GenericMessage)
async def admin_delete_note(
    user_id: str,
    note_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    note = await session.get(UserNote, note_id)
    if note is None or note.user_id != user_id:
        raise HTTPException(status_code=404, detail="not found")
    await session.delete(note)
    await record_audit(
        session,
        actor=actor.id,
        action="admin.user.note.delete",
        target_type="user",
        target_id=user_id,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return GenericMessage(message="deleted")


@router.get("/users/{user_id}/tags")
async def admin_list_tags(
    user_id: str,
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> list[str]:
    rows = list(
        (
            await session.scalars(
                select(UserTag).where(UserTag.user_id == user_id)
            )
        ).all()
    )
    return [t.tag for t in rows]


@router.post("/users/{user_id}/tags", response_model=GenericMessage)
async def admin_add_tag(
    user_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
    tag: str = Query(..., min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$"),
) -> GenericMessage:
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    existing = (
        await session.scalars(
            select(UserTag)
            .where(UserTag.user_id == user_id)
            .where(UserTag.tag == tag)
        )
    ).first()
    if existing is not None:
        return GenericMessage(message="exists")
    session.add(UserTag(user_id=user_id, tag=tag, created_by=actor.id))
    await record_audit(
        session,
        actor=actor.id,
        action="admin.user.tag.add",
        target_type="user",
        target_id=user_id,
        ip=request.client.host if request.client else None,
        after={"tag": tag},
    )
    await session.commit()
    return GenericMessage(message="added")


@router.delete("/users/{user_id}/tags/{tag}", response_model=GenericMessage)
async def admin_remove_tag(
    user_id: str,
    tag: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    row = (
        await session.scalars(
            select(UserTag)
            .where(UserTag.user_id == user_id)
            .where(UserTag.tag == tag)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    await session.delete(row)
    await record_audit(
        session,
        actor=actor.id,
        action="admin.user.tag.remove",
        target_type="user",
        target_id=user_id,
        ip=request.client.host if request.client else None,
        after={"tag": tag},
    )
    await session.commit()
    return GenericMessage(message="removed")


__all__ = ["router"]
