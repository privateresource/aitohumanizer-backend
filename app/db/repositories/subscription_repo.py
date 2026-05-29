import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.subscription import Subscription


class SubscriptionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_user(self, user_id: uuid.UUID) -> Optional[Subscription]:
        result = await self.session.execute(
            select(Subscription).where(
                Subscription.user_id == user_id,
                Subscription.status.in_(["active", "trialing", "paused"]),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, subscription_id: uuid.UUID) -> Optional[Subscription]:
        result = await self.session.execute(
            select(Subscription).where(Subscription.id == subscription_id)
        )
        return result.scalar_one_or_none()

    async def get_by_paddle_id(self, paddle_subscription_id: str) -> Optional[Subscription]:
        result = await self.session.execute(
            select(Subscription).where(
                Subscription.paddle_subscription_id == paddle_subscription_id
            )
        )
        return result.scalar_one_or_none()

    async def get_by_customer_id(self, customer_id: str) -> list[Subscription]:
        result = await self.session.execute(
            select(Subscription).where(
                Subscription.paddle_customer_id == customer_id
            )
        )
        return list(result.scalars().all())

    async def create(self, subscription: Subscription) -> Subscription:
        self.session.add(subscription)
        await self.session.commit()
        await self.session.refresh(subscription)
        return subscription

    async def update(self, subscription_id: uuid.UUID, data: dict) -> Optional[Subscription]:
        data["updated_at"] = datetime.now(timezone.utc)
        stmt = (
            update(Subscription)
            .where(Subscription.id == subscription_id)
            .values(**data)
            .returning(Subscription)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.scalar_one_or_none()

    async def cancel(self, subscription_id: uuid.UUID) -> Optional[Subscription]:
        return await self.update(
            subscription_id,
            {
                "status": "canceled",
                "cancelled_at": datetime.now(timezone.utc),
            },
        )

    async def change_plan(
        self, subscription_id: uuid.UUID, new_plan_id: uuid.UUID
    ) -> Optional[Subscription]:
        return await self.update(subscription_id, {"plan_id": new_plan_id})
