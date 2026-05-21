"""Admin system controls — maintenance, feature flags, IP blocklist, broadcast, scheduler.

Mọi endpoint require admin/owner. Maintenance + feature flags lưu trong
``AppConfig`` (key=`maintenance`, `feature_flags`). IP blocklist là bảng
riêng. Broadcast: gọi ``notify`` cho mỗi user thoả filter.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.config import runtime as config_runtime
from packages.db.models import IpBlocklist, Subscription, User
from packages.db.session import get_session
from packages.notifications.dispatcher import notify
from packages.obs import metrics
from packages.schemas.auth import GenericMessage
from packages.security.audit import record_audit
from packages.security.user_auth import current_admin_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/admin", tags=["admin-system"])


MAINTENANCE_KEY = "maintenance"
FEATURE_FLAGS_KEY = "feature_flags"


# ---------------------------------------------------------------------------
# MAINTENANCE
# ---------------------------------------------------------------------------


@router.get("/maintenance")
async def get_maintenance(
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    cfg = await config_runtime.get_config(session, MAINTENANCE_KEY)
    return {
        "enabled": bool(cfg.get("enabled")),
        "message": cfg.get("message", ""),
    }


@router.put("/maintenance", response_model=GenericMessage)
async def update_maintenance(
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
    enabled: bool = Query(False),
    message: str = Query(default="Hệ thống đang bảo trì", max_length=500),
) -> GenericMessage:
    await config_runtime.set_config(
        session,
        MAINTENANCE_KEY,
        {"enabled": enabled, "message": message},
        actor_id=actor.id,
    )
    await record_audit(
        session,
        actor=actor.id,
        action="admin.maintenance.update",
        target_type="app_config",
        target_id=MAINTENANCE_KEY,
        ip=request.client.host if request.client else None,
        after={"enabled": enabled, "message": message},
    )
    await session.commit()
    return GenericMessage(message="ok")


# ---------------------------------------------------------------------------
# FEATURE FLAGS
# ---------------------------------------------------------------------------


@router.get("/feature-flags")
async def get_feature_flags(
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    cfg = await config_runtime.get_config(session, FEATURE_FLAGS_KEY)
    return {k: bool(v) for k, v in cfg.items()}


@router.put("/feature-flags", response_model=GenericMessage)
async def update_feature_flag(
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
    flag: str = Query(..., min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$"),
    enabled: bool = Query(...),
) -> GenericMessage:
    cfg = await config_runtime.get_config(session, FEATURE_FLAGS_KEY)
    cfg[flag] = enabled
    await config_runtime.set_config(
        session, FEATURE_FLAGS_KEY, cfg, actor_id=actor.id
    )
    await record_audit(
        session,
        actor=actor.id,
        action="admin.feature_flag.update",
        target_type="app_config",
        target_id=FEATURE_FLAGS_KEY,
        ip=request.client.host if request.client else None,
        after={flag: enabled},
    )
    await session.commit()
    return GenericMessage(message="ok")


# ---------------------------------------------------------------------------
# IP BLOCKLIST
# ---------------------------------------------------------------------------


@router.get("/ip-blocklist")
async def list_ip_blocklist(
    limit: int = Query(100, ge=1, le=500),
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    rows = list(
        (
            await session.scalars(
                select(IpBlocklist)
                .order_by(desc(IpBlocklist.created_at))
                .limit(limit)
            )
        ).all()
    )
    return [
        {
            "id": r.id,
            "cidr": r.cidr,
            "reason": r.reason,
            "created_by": r.created_by,
            "expires_at": r.expires_at.isoformat() if r.expires_at else None,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.post("/ip-blocklist", response_model=GenericMessage)
async def add_ip_blocklist(
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
    cidr: str = Query(..., min_length=1, max_length=64),
    reason: str | None = Query(default=None, max_length=500),
) -> GenericMessage:
    import ipaddress

    try:
        ipaddress.ip_network(cidr, strict=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid cidr: {exc}") from exc

    existing = (
        await session.scalars(select(IpBlocklist).where(IpBlocklist.cidr == cidr))
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="cidr already blocked"
        )
    entry = IpBlocklist(cidr=cidr, reason=reason, created_by=actor.id)
    session.add(entry)
    await record_audit(
        session,
        actor=actor.id,
        action="admin.ip_blocklist.add",
        target_type="ip_blocklist",
        target_id=cidr,
        ip=request.client.host if request.client else None,
        after={"reason": reason},
    )
    await session.commit()
    return GenericMessage(message="blocked")


@router.delete("/ip-blocklist/{block_id}", response_model=GenericMessage)
async def remove_ip_blocklist(
    block_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    entry = await session.get(IpBlocklist, block_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="not found")
    cidr = entry.cidr
    await session.delete(entry)
    await record_audit(
        session,
        actor=actor.id,
        action="admin.ip_blocklist.remove",
        target_type="ip_blocklist",
        target_id=cidr,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return GenericMessage(message="unblocked")


# ---------------------------------------------------------------------------
# BROADCAST NOTIFICATION
# ---------------------------------------------------------------------------


@router.post("/notifications/broadcast")
async def broadcast_notification(
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
    title: str = Query(..., min_length=1, max_length=255),
    body: str = Query(..., min_length=1, max_length=2000),
    role: str | None = Query(default=None, pattern="^(user|admin|owner)$"),
    plan_code: str | None = Query(default=None, max_length=32),
    only_active: bool = Query(default=True),
) -> dict[str, Any]:
    """Gửi notification kind='announcement' cho user thoả filter.

    - role: nếu set, chỉ user có role này.
    - plan_code: nếu set, chỉ user có subscription active với plan_code này.
    - only_active: chỉ user status='active'.
    """
    stmt = select(User)
    if only_active:
        stmt = stmt.where(User.status == "active")
    if role:
        stmt = stmt.where(User.role == role)
    if plan_code:
        from packages.db.models import Plan

        plan = (
            await session.scalars(select(Plan).where(Plan.code == plan_code))
        ).first()
        if plan is None:
            raise HTTPException(status_code=404, detail="plan not found")
        sub_users = select(Subscription.user_id).where(
            Subscription.plan_id == plan.id, Subscription.status == "active"
        )
        stmt = stmt.where(User.id.in_(sub_users))

    users = list((await session.scalars(stmt)).all())
    sent = 0
    for user in users:
        try:
            await notify(
                session,
                user=user,
                kind="announcement",
                title=title,
                body=body,
            )
            sent += 1
        except Exception:  # noqa: BLE001
            logger.exception("broadcast_notify_failed", extra={"user_id": user.id})

    await record_audit(
        session,
        actor=actor.id,
        action="admin.broadcast.send",
        target_type="notification",
        target_id="*",
        ip=request.client.host if request.client else None,
        after={
            "filter": {"role": role, "plan_code": plan_code, "only_active": only_active},
            "title": title,
            "sent": sent,
        },
    )
    await session.commit()
    return {"sent": sent, "candidates": len(users)}


# ---------------------------------------------------------------------------
# SCHEDULER STATUS + CACHE
# ---------------------------------------------------------------------------


_KNOWN_JOBS = (
    "reconcile",
    "webhook",
    "notification-dispatch",
    "expire-subs",
    "expire-soon",
    "audit-retention",
)


@router.get("/scheduler")
async def scheduler_status(
    _: User = Depends(current_admin_user),
) -> dict[str, Any]:
    """Đọc Prom gauge ``apibank_scheduler_last_run_timestamp`` per-job."""
    now = time.time()
    jobs: list[dict[str, Any]] = []
    for job in _KNOWN_JOBS:
        try:
            labels = metrics.scheduler_last_run_timestamp.labels(job=job)
            ts = float(labels._value.get() or 0.0)
        except Exception:  # noqa: BLE001
            ts = 0.0
        age = max(0.0, now - ts) if ts > 0 else None
        jobs.append(
            {
                "job": job,
                "last_run_at": (
                    datetime.fromtimestamp(ts, UTC).isoformat() if ts > 0 else None
                ),
                "age_seconds": int(age) if age is not None else None,
            }
        )
    return {"jobs": jobs, "checked_at": datetime.now(UTC).isoformat()}


@router.post("/cache/invalidate", response_model=GenericMessage)
async def cache_invalidate(
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    """Purge cache config + clear LRU.

    Dùng khi hot-reload config mà không restart pod.
    """
    config_runtime.invalidate()
    # Clear PII cipher cache (in case key rotation runtime).
    try:
        from packages.security.pii import reset_cache_for_tests

        reset_cache_for_tests()
    except Exception:  # noqa: BLE001,S110
        logger.debug("pii_cache_reset_skipped", exc_info=True)
    await record_audit(
        session,
        actor=actor.id,
        action="admin.cache.invalidate",
        target_type="cache",
        target_id="all",
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return GenericMessage(message="invalidated")


# ---------------------------------------------------------------------------
# HEALTH (admin verbose)
# ---------------------------------------------------------------------------


@router.get("/health")
async def admin_health(
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Verbose health cho admin dashboard (DB, Redis, Fernet, scheduler, poller)."""
    from packages.config.settings import get_settings
    from packages.db.models import BankAccount

    out: dict[str, Any] = {}
    # DB ping qua session caller-injected.
    try:
        from sqlalchemy import text

        await session.execute(text("SELECT 1"))
        out["db"] = "ok"
    except Exception as exc:  # noqa: BLE001
        out["db"] = f"fail: {exc!r}"

    # Redis
    try:
        from collections.abc import Awaitable
        from typing import cast

        from redis.asyncio import Redis

        redis = Redis.from_url(get_settings().redis_url)
        await cast(Awaitable[Any], redis.ping())
        await redis.aclose()
        out["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        out["redis"] = f"fail: {exc!r}"

    # Bank polling status summary
    try:
        rows = (
            await session.execute(
                select(BankAccount.polling_status, func.count())
                .where(BankAccount.status != "deleted")
                .group_by(BankAccount.polling_status)
            )
        ).all()
        out["bank_polling"] = {row[0]: int(row[1]) for row in rows}
    except Exception as exc:  # noqa: BLE001
        out["bank_polling"] = f"fail: {exc!r}"

    # Scheduler ages.
    out["scheduler"] = (await scheduler_status())["jobs"]

    return out


@router.get("/roles/permissions")
async def admin_role_catalog(
    _: User = Depends(current_admin_user),
) -> dict[str, list[str]]:
    """Trả về catalog role → list permissions cho FE render matrix."""
    from packages.security.permissions import PERMISSIONS

    return {role: sorted(perms) for role, perms in PERMISSIONS.items()}


# ---------------------------------------------------------------------------
# ADMIN SECURITY (IP allowlist + 2FA enforcement) + sessions list
# ---------------------------------------------------------------------------


ADMIN_SECURITY_KEY = "admin_security"


@router.get("/security/config")
async def get_admin_security(
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    cfg = await config_runtime.get_config(session, ADMIN_SECURITY_KEY)
    return {
        "ip_allowlist": list(cfg.get("ip_allowlist") or []),
        "require_2fa": bool(cfg.get("require_2fa")),
    }


@router.put("/security/config", response_model=GenericMessage)
async def update_admin_security(
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
    require_2fa: bool = Query(default=False),
    ip_allowlist: list[str] = Query(default=[]),
) -> GenericMessage:
    import ipaddress

    for cidr in ip_allowlist:
        try:
            ipaddress.ip_network(cidr, strict=False)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"invalid cidr {cidr}: {exc}"
            ) from exc
    payload = {"ip_allowlist": list(ip_allowlist), "require_2fa": require_2fa}
    await config_runtime.set_config(
        session, ADMIN_SECURITY_KEY, payload, actor_id=actor.id
    )
    await record_audit(
        session,
        actor=actor.id,
        action="admin.security.update",
        target_type="app_config",
        target_id=ADMIN_SECURITY_KEY,
        ip=request.client.host if request.client else None,
        after=payload,
    )
    await session.commit()
    return GenericMessage(message="ok")


@router.get("/admin-sessions")
async def list_admin_sessions(
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """List session hiện active của user role admin/owner."""
    from packages.db.models import Session as SessionModel

    rows = (
        await session.execute(
            select(SessionModel, User.email, User.role)
            .join(User, User.id == SessionModel.user_id)
            .where(User.role.in_(("admin", "owner")))
            .where(SessionModel.revoked_at.is_(None))
            .order_by(desc(SessionModel.last_seen_at))
        )
    ).all()
    return [
        {
            "id": s.id,
            "user_id": s.user_id,
            "user_email": email,
            "role": role,
            "ip": s.ip,
            "user_agent": s.user_agent,
            "last_seen_at": s.last_seen_at.isoformat(),
            "expires_at": s.expires_at.isoformat(),
            "created_at": s.created_at.isoformat(),
        }
        for s, email, role in rows
    ]


@router.delete("/admin-sessions/{session_id}", response_model=GenericMessage)
async def revoke_admin_session(
    session_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    from packages.security.sessions import revoke_session

    ok = await revoke_session(session, session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="not found")
    await record_audit(
        session,
        actor=actor.id,
        action="admin.admin_session.revoke",
        target_type="session",
        target_id=session_id,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return GenericMessage(message="revoked")


# ---------------------------------------------------------------------------
# AUDIT LOG EXPORT
# ---------------------------------------------------------------------------


@router.get("/audit-log/export")
async def admin_audit_log_export(
    action: str | None = None,
    actor: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    fmt: str = Query(default="csv", pattern="^(csv|json)$"),
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    import csv
    import io
    import json
    from collections.abc import AsyncIterator

    from fastapi.responses import StreamingResponse

    from packages.db.models import AuditLog

    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action.like(f"{action}%"))
    if actor:
        stmt = stmt.where(AuditLog.actor == actor)
    if target_type:
        stmt = stmt.where(AuditLog.target_type == target_type)
    if target_id:
        stmt = stmt.where(AuditLog.target_id == target_id)
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= date_from)
    if date_to:
        stmt = stmt.where(AuditLog.created_at <= date_to)
    stmt = stmt.order_by(desc(AuditLog.created_at))

    rows = list((await session.scalars(stmt)).all())

    if fmt == "json":

        async def _gen_json() -> AsyncIterator[bytes]:
            yield b"["
            first = True
            for r in rows:
                obj = {
                    "id": r.id,
                    "actor": r.actor,
                    "action": r.action,
                    "target_type": r.target_type,
                    "target_id": r.target_id,
                    "ip": r.ip,
                    "before": r.before_json,
                    "after": r.after_json,
                    "created_at": r.created_at.isoformat(),
                }
                if not first:
                    yield b","
                first = False
                yield json.dumps(obj, ensure_ascii=False).encode("utf-8")
            yield b"]"

        return StreamingResponse(
            _gen_json(),
            media_type="application/json",
            headers={
                "Content-Disposition": "attachment; filename=audit-log.json"
            },
        )

    async def _gen_csv() -> AsyncIterator[bytes]:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "id",
                "actor",
                "action",
                "target_type",
                "target_id",
                "ip",
                "created_at",
            ]
        )
        yield buf.getvalue().encode("utf-8")
        buf.seek(0)
        buf.truncate(0)
        for r in rows:
            writer.writerow(
                [
                    r.id,
                    r.actor,
                    r.action,
                    r.target_type,
                    r.target_id,
                    r.ip or "",
                    r.created_at.isoformat(),
                ]
            )
            yield buf.getvalue().encode("utf-8")
            buf.seek(0)
            buf.truncate(0)

    return StreamingResponse(
        _gen_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit-log.csv"},
    )


# ---------------------------------------------------------------------------
# NOTIFICATIONS — send single + templates
# ---------------------------------------------------------------------------


@router.post("/users/{user_id}:notify", response_model=GenericMessage)
async def admin_notify_user(
    user_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
    title: str = Query(..., min_length=1, max_length=255),
    body: str = Query(..., min_length=1, max_length=4000),
    kind: str = Query(default="admin_message", min_length=1, max_length=64),
) -> GenericMessage:
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    await notify(
        session,
        user=target,
        kind=kind,
        title=title,
        body=body,
    )
    await record_audit(
        session,
        actor=actor.id,
        action="admin.notification.send",
        target_type="user",
        target_id=user_id,
        ip=request.client.host if request.client else None,
        after={"kind": kind, "title": title},
    )
    await session.commit()
    return GenericMessage(message="sent")


@router.get("/notification-templates")
async def list_notification_templates(
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    from packages.db.models import NotificationTemplate

    rows = list(
        (
            await session.scalars(
                select(NotificationTemplate).order_by(NotificationTemplate.code)
            )
        ).all()
    )
    return [
        {
            "id": t.id,
            "code": t.code,
            "title": t.title,
            "body_md": t.body_md,
            "description": t.description,
            "updated_at": t.updated_at.isoformat(),
        }
        for t in rows
    ]


@router.post("/notification-templates", response_model=GenericMessage)
async def upsert_notification_template(
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
    code: str = Query(..., min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$"),
    title: str = Query(..., min_length=1, max_length=255),
    body_md: str = Query(..., min_length=1, max_length=10_000),
    description: str | None = Query(default=None, max_length=500),
) -> GenericMessage:
    from packages.db.models import NotificationTemplate

    existing = (
        await session.scalars(
            select(NotificationTemplate).where(NotificationTemplate.code == code)
        )
    ).first()
    if existing is None:
        existing = NotificationTemplate(
            code=code,
            title=title,
            body_md=body_md,
            description=description,
            created_by=actor.id,
        )
        session.add(existing)
        action = "create"
    else:
        existing.title = title
        existing.body_md = body_md
        existing.description = description
        action = "update"
    await record_audit(
        session,
        actor=actor.id,
        action=f"admin.notification_template.{action}",
        target_type="notification_template",
        target_id=code,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return GenericMessage(message=action)


@router.delete("/notification-templates/{code}", response_model=GenericMessage)
async def delete_notification_template(
    code: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    from packages.db.models import NotificationTemplate

    row = (
        await session.scalars(
            select(NotificationTemplate).where(NotificationTemplate.code == code)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    await session.delete(row)
    await record_audit(
        session,
        actor=actor.id,
        action="admin.notification_template.delete",
        target_type="notification_template",
        target_id=code,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return GenericMessage(message="deleted")


__all__ = ["router"]
