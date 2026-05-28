import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User
from app.db.models.subscription import Subscription
from app.db.models.humanize_request import HumanizeRequest
from app.db.models.word_usage import WordUsage
from app.db.models.admin_invite import AdminInvite


class AdminRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_dashboard_stats(self) -> dict:
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = today_start.replace(day=1)

        total_users_result = await self.session.execute(
            select(func.count(User.id))
        )
        total_users = total_users_result.scalar_one()

        new_users_today_result = await self.session.execute(
            select(func.count(User.id)).where(User.created_at >= today_start)
        )
        new_users_today = new_users_today_result.scalar_one()

        new_users_this_month_result = await self.session.execute(
            select(func.count(User.id)).where(User.created_at >= month_start)
        )
        new_users_this_month = new_users_this_month_result.scalar_one()

        active_subscriptions_result = await self.session.execute(
            select(func.count(Subscription.id)).where(
                Subscription.status.in_(["active", "trialing"])
            )
        )
        active_subscriptions = active_subscriptions_result.scalar_one()

        total_requests_result = await self.session.execute(
            select(func.count(HumanizeRequest.id))
        )
        total_requests = total_requests_result.scalar_one()

        requests_today_result = await self.session.execute(
            select(func.count(HumanizeRequest.id)).where(
                HumanizeRequest.created_at >= today_start
            )
        )
        requests_today = requests_today_result.scalar_one()

        total_words_result = await self.session.execute(
            select(func.coalesce(func.sum(HumanizeRequest.word_count), 0))
        )
        total_words = total_words_result.scalar_one()

        words_today_result = await self.session.execute(
            select(func.coalesce(func.sum(HumanizeRequest.word_count), 0)).where(
                HumanizeRequest.created_at >= today_start
            )
        )
        words_today = words_today_result.scalar_one()

        return {
            "total_users": total_users,
            "new_users_today": new_users_today,
            "new_users_this_month": new_users_this_month,
            "active_subscriptions": active_subscriptions,
            "total_requests": total_requests,
            "requests_today": requests_today,
            "total_words": total_words,
            "words_today": words_today,
        }

    async def get_revenue_stats(self) -> dict:
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        total_subscriptions_result = await self.session.execute(
            select(func.count(Subscription.id)).where(
                Subscription.status.in_(["active", "trialing", "paused"])
            )
        )
        total_active = total_subscriptions_result.scalar_one()

        new_this_month_result = await self.session.execute(
            select(func.count(Subscription.id)).where(
                and_(
                    Subscription.status.in_(["active", "trialing"]),
                    Subscription.created_at >= month_start,
                )
            )
        )
        new_this_month = new_this_month_result.scalar_one()

        return {
            "total_active_subscriptions": total_active,
            "new_subscriptions_this_month": new_this_month,
        }

    async def create_invite(self, invite: AdminInvite) -> AdminInvite:
        self.session.add(invite)
        await self.session.commit()
        await self.session.refresh(invite)
        return invite

    async def get_invite_by_token(self, token: str) -> Optional[AdminInvite]:
        result = await self.session.execute(
            select(AdminInvite).where(AdminInvite.token == token)
        )
        return result.scalar_one_or_none()

    async def mark_invite_used(
        self, invite_id: uuid.UUID, user_id: uuid.UUID
    ) -> Optional[AdminInvite]:
        result = await self.session.execute(
            select(AdminInvite).where(AdminInvite.id == invite_id)
        )
        invite = result.scalar_one_or_none()
        if not invite:
            return None

        invite.is_used = True
        invite.used_at = datetime.now(timezone.utc)
        invite.used_by_user_id = user_id
        await self.session.commit()
        await self.session.refresh(invite)
        return invite
