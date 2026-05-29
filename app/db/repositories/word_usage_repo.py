import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, func, and_, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.word_usage import WordUsage


class WordUsageRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_balance(
        self, user_id: uuid.UUID, plan_words_per_month: int
    ) -> int:
        if plan_words_per_month == -1:
            return 999999999

        period = datetime.now(timezone.utc).strftime("%Y-%m")
        result = await self.session.execute(
            select(func.coalesce(func.sum(WordUsage.words_delta), 0)).where(
                and_(
                    WordUsage.user_id == user_id,
                    WordUsage.billing_period == period,
                )
            )
        )
        delta_total = result.scalar_one()

        remaining = plan_words_per_month + delta_total
        return max(0, int(remaining))

    async def get_period_usage(
        self, user_id: uuid.UUID, period_start: datetime, period_end: datetime
    ) -> int:
        result = await self.session.execute(
            select(func.coalesce(func.sum(case((WordUsage.event_type == "humanize_use", -WordUsage.words_delta), else_=0)), 0)).where(
                and_(
                    WordUsage.user_id == user_id,
                    WordUsage.event_type == "humanize_use",
                    WordUsage.created_at >= period_start,
                    WordUsage.created_at < period_end,
                )
            )
        )
        return result.scalar_one()

    async def add_entry(self, entry: WordUsage) -> WordUsage:
        self.session.add(entry)
        await self.session.commit()
        await self.session.refresh(entry)
        return entry

    async def get_usage_history(
        self,
        user_id: uuid.UUID,
        skip: int = 0,
        limit: int = 50,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> tuple[list[WordUsage], int]:
        query = select(WordUsage)
        count_query = select(func.count(WordUsage.id))

        conditions = [WordUsage.user_id == user_id]
        if start_date:
            conditions.append(WordUsage.created_at >= start_date)
        if end_date:
            conditions.append(WordUsage.created_at <= end_date)

        query = query.where(and_(*conditions))
        count_query = count_query.where(and_(*conditions))

        total_result = await self.session.execute(count_query)
        total = total_result.scalar_one()

        query = query.order_by(WordUsage.created_at.desc()).offset(skip).limit(limit)
        result = await self.session.execute(query)
        entries = list(result.scalars().all())

        return entries, total
