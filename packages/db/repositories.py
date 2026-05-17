from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import Order, Transaction, Webhook
from packages.schemas.orders import OrderCreate
from packages.schemas.webhooks import WebhookCreate


async def _get_webhook(session: AsyncSession, webhook_id: str) -> Webhook | None:
    return await session.get(Webhook, webhook_id)


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_order(self, payload: OrderCreate, *, idempotency_key: str) -> Order:
        order = Order.new(
            amount_vnd=payload.amount_vnd,
            bank_account_id=payload.bank_account_id,
            ttl_seconds=payload.ttl_seconds,
            description=payload.description,
            customer_ref=payload.customer_ref,
            metadata_json=payload.metadata,
        )
        self._session.add(order)
        await self._session.commit()
        await self._session.refresh(order)
        return order

    async def get_order(self, order_id: str) -> Order | None:
        return await self._session.get(Order, order_id)

    async def cancel_order(self, order_id: str) -> Order | None:
        order = await self.get_order(order_id)
        if order is None:
            return None
        if order.status == "pending":
            order.status = "canceled"
            order.updated_at = datetime.now(UTC)
            await self._session.commit()
            await self._session.refresh(order)
        return order


class TransactionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_transactions(
        self,
        *,
        from_: datetime | None,
        to: datetime | None,
        account: str | None,
        user_id: str | None = None,
    ) -> list[Transaction]:
        stmt: Select[tuple[Transaction]] = select(Transaction).order_by(
            Transaction.posted_at.desc()
        )
        if from_ is not None:
            stmt = stmt.where(Transaction.posted_at >= from_)
        if to is not None:
            stmt = stmt.where(Transaction.posted_at <= to)
        if account is not None:
            stmt = stmt.where(Transaction.bank_account_id == account)
        if user_id is not None:
            # Multi-tenant: chỉ trả tx thuộc bank account của user_id.
            from packages.db.models import BankAccount

            user_banks = select(BankAccount.id).where(BankAccount.user_id == user_id)
            stmt = stmt.where(Transaction.bank_account_id.in_(user_banks))
        return list((await self._session.scalars(stmt)).all())


class WebhookRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_webhook(self, payload: WebhookCreate) -> Webhook:
        webhook = Webhook(
            url=str(payload.url),
            secret_enc=payload.secret,
            active=payload.active,
            headers_json=payload.headers,
        )
        self._session.add(webhook)
        await self._session.commit()
        await self._session.refresh(webhook)
        return webhook

    async def list_webhooks(self) -> list[Webhook]:
        return list((await self._session.scalars(select(Webhook))).all())
