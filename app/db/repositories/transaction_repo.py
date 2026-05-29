import uuid
from typing import Optional
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.transaction import Transaction


class TransactionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_user(
        self,
        user_id: uuid.UUID,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[Transaction], int]:
        query = select(Transaction).where(Transaction.user_id == user_id)
        count_query = select(func.count(Transaction.id)).where(Transaction.user_id == user_id)

        total_result = await self.session.execute(count_query)
        total = total_result.scalar_one()

        query = query.order_by(Transaction.paid_at.desc().nulls_last(), Transaction.created_at.desc()).offset(skip).limit(limit)
        result = await self.session.execute(query)
        txns = list(result.scalars().all())

        return txns, total

    async def get_by_paddle_id(self, paddle_transaction_id: str) -> Optional[Transaction]:
        result = await self.session.execute(
            select(Transaction).where(Transaction.paddle_transaction_id == paddle_transaction_id)
        )
        return result.scalar_one_or_none()

    async def upsert_from_paddle(
        self,
        user_id: uuid.UUID,
        paddle_id: str,
        customer_id: Optional[str],
        plan_name: Optional[str],
        billing_cycle: Optional[str],
        status: str,
        amount: Decimal,
        currency: str,
        payment_method: Optional[str],
        invoice_url: Optional[str],
        receipt_url: Optional[str],
        paid_at: Optional[datetime],
    ) -> Transaction:
        existing = await self.get_by_paddle_id(paddle_id)
        if existing:
            existing.status = status
            existing.invoice_url = invoice_url or existing.invoice_url
            existing.receipt_url = receipt_url or existing.receipt_url
            existing.paid_at = paid_at or existing.paid_at
            await self.session.commit()
            await self.session.refresh(existing)
            return existing

        txn = Transaction(
            user_id=user_id,
            paddle_transaction_id=paddle_id,
            paddle_customer_id=customer_id,
            plan_name=plan_name,
            billing_cycle=billing_cycle,
            status=status,
            amount=amount,
            currency=currency,
            payment_method=payment_method,
            invoice_url=invoice_url,
            receipt_url=receipt_url,
            paid_at=paid_at,
        )
        self.session.add(txn)
        await self.session.commit()
        await self.session.refresh(txn)
        return txn

    async def list_all(
        self,
        skip: int = 0,
        limit: int = 50,
        status_filter: Optional[str] = None,
    ) -> tuple[list[Transaction], int]:
        conditions = []
        if status_filter:
            conditions.append(Transaction.status == status_filter)

        query = select(Transaction)
        count_query = select(func.count(Transaction.id))

        if conditions:
            query = query.where(and_(*conditions))
            count_query = count_query.where(and_(*conditions))

        total_result = await self.session.execute(count_query)
        total = total_result.scalar_one()

        query = query.order_by(Transaction.paid_at.desc().nulls_last(), Transaction.created_at.desc()).offset(skip).limit(limit)
        result = await self.session.execute(query)
        txns = list(result.scalars().all())

        return txns, total
