from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_admin_user
from app.db.models.user import User
from app.db.repositories.admin_repo import AdminRepository

router = APIRouter(prefix="/admin/dashboard", tags=["admin"])


class DashboardResponse(BaseModel):
    total_users: int
    new_users_today: int
    new_users_this_month: int
    active_subscriptions: int
    total_requests: int
    requests_today: int
    total_words: int
    words_today: int
    mrr: float
    arr: float
    churn_rate: float
    llm_status: str
    updated_at: str


@router.get("", response_model=DashboardResponse)
async def get_dashboard(
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    repo = AdminRepository(session)
    stats = await repo.get_dashboard_stats()
    revenue = await repo.get_revenue_stats()

    mrr = 0.0
    arr = 0.0
    churn_rate = 0.0

    try:
        from app.db.models.plan import Plan
        from app.db.models.subscription import Subscription
        from sqlalchemy import select, func

        monthly_result = await session.execute(
            select(func.coalesce(func.sum(Plan.price_monthly), 0)).select_from(
                Subscription
            ).join(Plan, Subscription.plan_id == Plan.id).where(
                Subscription.status.in_(["active", "trialing"])
            )
        )
        mrr = round(float(monthly_result.scalar_one()), 2)
        arr = round(mrr * 12, 2)

        total_subs_result = await session.execute(
            select(func.count(Subscription.id))
        )
        total_subs = total_subs_result.scalar_one()
        if total_subs > 0:
            now = datetime.now(timezone.utc)
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            canceled_this_month_result = await session.execute(
                select(func.count(Subscription.id)).where(
                    Subscription.status == "canceled",
                    Subscription.cancelled_at >= month_start,
                )
            )
            canceled = canceled_this_month_result.scalar_one()
            churn_rate = round(canceled / total_subs * 100, 2) if total_subs > 0 else 0.0
    except Exception:
        pass

    return DashboardResponse(
        total_users=stats["total_users"],
        new_users_today=stats["new_users_today"],
        new_users_this_month=stats["new_users_this_month"],
        active_subscriptions=stats["active_subscriptions"],
        total_requests=stats["total_requests"],
        requests_today=stats["requests_today"],
        total_words=stats["total_words"],
        words_today=stats["words_today"],
        mrr=mrr,
        arr=arr,
        churn_rate=churn_rate,
        llm_status="operational",
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
