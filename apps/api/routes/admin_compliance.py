"""Admin compliance — retention policy, GDPR data export queue, legal versions.

Phase 3. Mọi endpoint require admin/owner.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.config import runtime as config_runtime
from packages.db.models import (
    DataExportRequest,
    LegalVersion,
    TermsAcceptance,
    User,
)
from packages.db.session import get_session
from packages.schemas.auth import GenericMessage
from packages.security.audit import record_audit
from packages.security.user_auth import current_admin_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/admin", tags=["admin-compliance"])

RETENTION_KEY = "retention"


# ---------------------------------------------------------------------------
# RETENTION
# ---------------------------------------------------------------------------


@router.get("/compliance/retention")
async def get_retention(
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    cfg = await config_runtime.get_config(session, RETENTION_KEY)
    return {
        "audit_log_days": int(cfg.get("audit_log_days") or 0),
        "tx_raw_days": int(cfg.get("tx_raw_days") or 0),
        "notification_days": int(cfg.get("notification_days") or 0),
    }


@router.put("/compliance/retention", response_model=GenericMessage)
async def update_retention(
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
    audit_log_days: int = Query(default=0, ge=0, le=3650),
    tx_raw_days: int = Query(default=0, ge=0, le=3650),
    notification_days: int = Query(default=0, ge=0, le=3650),
) -> GenericMessage:
    payload = {
        "audit_log_days": audit_log_days,
        "tx_raw_days": tx_raw_days,
        "notification_days": notification_days,
    }
    await config_runtime.set_config(
        session, RETENTION_KEY, payload, actor_id=actor.id
    )
    await record_audit(
        session,
        actor=actor.id,
        action="admin.retention.update",
        target_type="app_config",
        target_id=RETENTION_KEY,
        ip=request.client.host if request.client else None,
        after=payload,
    )
    await session.commit()
    return GenericMessage(message="ok")


# ---------------------------------------------------------------------------
# DATA EXPORT REQUESTS (GDPR)
# ---------------------------------------------------------------------------


@router.get("/compliance/data-exports")
async def list_data_exports(
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    stmt = select(DataExportRequest, User.email).outerjoin(
        User, User.id == DataExportRequest.user_id
    )
    if status:
        stmt = stmt.where(DataExportRequest.status == status)
    stmt = stmt.order_by(desc(DataExportRequest.requested_at)).limit(limit)
    rows = (await session.execute(stmt)).all()
    return [
        {
            "id": r.id,
            "user_id": r.user_id,
            "user_email": email,
            "status": r.status,
            "file_path": r.file_path,
            "error": r.error,
            "requested_at": r.requested_at.isoformat(),
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "expires_at": r.expires_at.isoformat() if r.expires_at else None,
        }
        for r, email in rows
    ]


@router.post("/compliance/data-exports/{request_id}:fulfill", response_model=GenericMessage)
async def fulfill_data_export(
    request_id: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    """Sinh ZIP data export cho 1 request → set status='ready'.

    Sync helper :mod:`packages.compliance.data_export` build payload tổng hợp
    user/sessions/api_keys/orders/transactions/invoices/wallet_tx/notifications.
    """
    req = await session.get(DataExportRequest, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="not found")
    user = await session.get(User, req.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="user gone")

    from datetime import timedelta

    from packages.compliance import data_export

    try:
        path = await data_export.build_zip_for_user(session, user)
    except Exception as exc:  # noqa: BLE001
        req.status = "failed"
        req.error = f"{type(exc).__name__}: {exc}"[:500]
        await session.commit()
        raise HTTPException(status_code=500, detail=f"export failed: {exc}") from exc

    req.status = "ready"
    req.file_path = path
    req.completed_at = datetime.now(UTC)
    req.expires_at = req.completed_at + timedelta(days=7)
    await record_audit(
        session,
        actor=actor.id,
        action="admin.data_export.fulfill",
        target_type="data_export_request",
        target_id=request_id,
        ip=request.client.host if request.client else None,
        after={"file_path": path},
    )
    await session.commit()
    return GenericMessage(message="ready")


# ---------------------------------------------------------------------------
# LEGAL VERSIONS + TERMS ACCEPTANCES
# ---------------------------------------------------------------------------


@router.get("/compliance/legal/{kind}")
async def list_legal_versions(
    kind: str,
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    if kind not in ("terms", "privacy"):
        raise HTTPException(status_code=400, detail="kind invalid")
    rows = list(
        (
            await session.scalars(
                select(LegalVersion)
                .where(LegalVersion.kind == kind)
                .order_by(desc(LegalVersion.effective_at))
            )
        ).all()
    )
    return [
        {
            "id": r.id,
            "kind": r.kind,
            "version": r.version,
            "effective_at": r.effective_at.isoformat(),
            "created_by": r.created_by,
        }
        for r in rows
    ]


@router.post("/compliance/legal/{kind}", response_model=GenericMessage)
async def publish_legal_version(
    kind: str,
    request: Request,
    actor: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
    version: str = Query(..., min_length=1, max_length=32),
    content_md: str = Query(..., min_length=1, max_length=200_000),
) -> GenericMessage:
    if kind not in ("terms", "privacy"):
        raise HTTPException(status_code=400, detail="kind invalid")
    row = LegalVersion(
        kind=kind,
        version=version,
        content_md=content_md,
        created_by=actor.id,
    )
    session.add(row)
    await record_audit(
        session,
        actor=actor.id,
        action="admin.legal.publish",
        target_type="legal_version",
        target_id=f"{kind}:{version}",
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return GenericMessage(message="published")


@router.get("/compliance/terms-acceptances")
async def list_terms_acceptances(
    user_id: str | None = None,
    kind: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    stmt = select(TermsAcceptance, User.email).outerjoin(
        User, User.id == TermsAcceptance.user_id
    )
    if user_id:
        stmt = stmt.where(TermsAcceptance.user_id == user_id)
    if kind:
        stmt = stmt.where(TermsAcceptance.kind == kind)
    stmt = stmt.order_by(desc(TermsAcceptance.accepted_at)).limit(limit)
    rows = (await session.execute(stmt)).all()
    return [
        {
            "id": r.id,
            "user_id": r.user_id,
            "user_email": email,
            "kind": r.kind,
            "version": r.version,
            "accepted_at": r.accepted_at.isoformat(),
            "ip": r.ip,
        }
        for r, email in rows
    ]


__all__ = ["router"]
