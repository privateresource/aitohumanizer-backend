import uuid
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.plan import Plan


class PlanRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_all_active(self, include_hidden: bool = False) -> list[Plan]:
        query = select(Plan).where(Plan.is_active == True)
        query = query.order_by(Plan.sort_order.asc())
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_by_slug(self, slug: str) -> Optional[Plan]:
        result = await self.session.execute(select(Plan).where(Plan.slug == slug))
        return result.scalar_one_or_none()

    async def get_by_id(self, plan_id: uuid.UUID) -> Optional[Plan]:
        result = await self.session.execute(select(Plan).where(Plan.id == plan_id))
        return result.scalar_one_or_none()

    async def create(self, plan: Plan) -> Plan:
        self.session.add(plan)
        await self.session.commit()
        await self.session.refresh(plan)
        return plan

    async def update(self, plan_id: uuid.UUID, data: dict) -> Optional[Plan]:
        stmt = update(Plan).where(Plan.id == plan_id).values(**data).returning(Plan)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.scalar_one_or_none()

    async def get_by_paddle_price_id(self, price_id: str) -> Optional[Plan]:
        result = await self.session.execute(
            select(Plan).where(
                (Plan.paddle_price_id_monthly == price_id) | (Plan.paddle_price_id_yearly == price_id)
            )
        )
        return result.scalar_one_or_none()

    async def deactivate(self, plan_id: uuid.UUID) -> Optional[Plan]:
        return await self.update(plan_id, {"is_active": False})
