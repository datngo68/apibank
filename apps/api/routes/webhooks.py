from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import ApiKey, Webhook, WebhookAttempt, utcnow
from packages.db.repositories import WebhookRepository
from packages.db.session import get_session
from packages.schemas.webhooks import WebhookCreate, WebhookRead
from packages.security.dependencies import authenticated_api_key
from packages.webhook import encrypt_webhook_secret, validate_webhook_url

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _require_scope(api_key: ApiKey, scope: str) -> None:
    scopes = api_key.scopes or []
    if scope not in scopes and "admin:*" not in scopes:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="missing scope")


@router.post("", response_model=WebhookRead, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    payload: WebhookCreate,
    session: AsyncSession = Depends(get_session),
    api_key: ApiKey = Depends(authenticated_api_key),
) -> WebhookRead:
    _require_scope(api_key, "admin:*")
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
        url=str(payload.url),
        secret_enc=secret_value,
        active=payload.active,
        headers_json=payload.headers,
    )
    session.add(webhook)
    await session.commit()
    await session.refresh(webhook)
    return WebhookRead.model_validate(webhook)


@router.get("", response_model=list[WebhookRead])
async def list_webhooks(
    session: AsyncSession = Depends(get_session),
    api_key: ApiKey = Depends(authenticated_api_key),
) -> list[WebhookRead]:
    _require_scope(api_key, "admin:*")
    repo = WebhookRepository(session)
    rows = await repo.list_webhooks()
    return [WebhookRead.model_validate(row) for row in rows]


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    webhook_id: str,
    session: AsyncSession = Depends(get_session),
    api_key: ApiKey = Depends(authenticated_api_key),
) -> None:
    _require_scope(api_key, "admin:*")
    webhook = await session.get(Webhook, webhook_id)
    if webhook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="webhook not found")
    webhook.active = False
    await session.commit()


@router.post("/attempts/{attempt_id}:replay", status_code=status.HTTP_202_ACCEPTED)
async def replay_attempt(
    attempt_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    api_key: ApiKey = Depends(authenticated_api_key),
) -> dict[str, str]:
    _ = request
    _require_scope(api_key, "admin:*")
    attempt = await session.get(WebhookAttempt, attempt_id)
    if attempt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="attempt not found")
    attempt.status = "pending"
    attempt.next_run_at = utcnow()
    attempt.last_error = None
    await session.commit()
    return {"status": "queued", "attempt_id": attempt.id}
