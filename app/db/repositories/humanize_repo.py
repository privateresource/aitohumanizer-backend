import uuid
from typing import Optional

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.humanize_request import HumanizeRequest


class HumanizeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, request: HumanizeRequest) -> HumanizeRequest:
        self.session.add(request)
        await self.session.commit()
        await self.session.refresh(request)
        return request

    async def get_by_user(
        self,
        user_id: uuid.UUID,
        skip: int = 0,
        limit: int = 50,
        mode: Optional[str] = None,
    ) -> tuple[list[HumanizeRequest], int]:
        query = select(HumanizeRequest)
        count_query = select(func.count(HumanizeRequest.id))

        conditions = [HumanizeRequest.user_id == user_id]
        if mode:
            conditions.append(HumanizeRequest.mode == mode)

        query = query.where(and_(*conditions))
        count_query = count_query.where(and_(*conditions))

        total_result = await self.session.execute(count_query)
        total = total_result.scalar_one()

        query = query.order_by(HumanizeRequest.created_at.desc()).offset(skip).limit(limit)
        result = await self.session.execute(query)
        requests = list(result.scalars().all())

        return requests, total

    async def get_by_session(
        self, session_id: str, skip: int = 0, limit: int = 50
    ) -> tuple[list[HumanizeRequest], int]:
        query = select(HumanizeRequest).where(
            HumanizeRequest.anonymous_session_id == session_id
        )
        count_query = select(func.count(HumanizeRequest.id)).where(
            HumanizeRequest.anonymous_session_id == session_id
        )

        total_result = await self.session.execute(count_query)
        total = total_result.scalar_one()

        query = query.order_by(HumanizeRequest.created_at.desc()).offset(skip).limit(limit)
        result = await self.session.execute(query)
        requests = list(result.scalars().all())

        return requests, total

    async def get_stats(self, user_id: uuid.UUID) -> dict:
        total_query = select(func.count(HumanizeRequest.id)).where(
            HumanizeRequest.user_id == user_id
        )
        total_result = await self.session.execute(total_query)
        total = total_result.scalar_one()

        words_query = select(func.coalesce(func.sum(HumanizeRequest.word_count), 0)).where(
            HumanizeRequest.user_id == user_id
        )
        words_result = await self.session.execute(words_query)
        total_words = words_result.scalar_one()

        avg_time_query = select(func.coalesce(func.avg(HumanizeRequest.processing_time_ms), 0)).where(
            and_(
                HumanizeRequest.user_id == user_id,
                HumanizeRequest.processing_time_ms.isnot(None),
            )
        )
        avg_time_result = await self.session.execute(avg_time_query)
        avg_time = round(avg_time_result.scalar_one(), 2)

        return {
            "total_requests": total,
            "total_words": total_words,
            "avg_processing_time_ms": avg_time,
        }
