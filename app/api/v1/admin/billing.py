import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.deps import get_db_session, get_admin_user
from app.core.exceptions import BadRequestException, NotFoundException
from app.db.models.user import User
from app.db.models.subscription import Subscription
from app.db.models.plan import Plan
from app.db.repositories.subscription_repo import SubscriptionRepository
from app.db.repositories.plan_repo import PlanRepository
from app.db.repositories.admin_repo import AdminRepository
from app.billing.paddle_client import (
    cancel_subscription as paddle_cancel,
    get_subscription as paddle_get_sub,
)

router = APIRouter(prefix="/admin/billing", tags=["admin"])


class PlanSummary(BaseModel):
    id: str
    name: str
    slug: str
    price_monthly: float
    price_yearly: float


class UserSummary(BaseModel):
    id: str
    email: str
    full_name: Optional[str] = None


class SubscriptionItem(BaseModel):
    id: str
    user: UserSummary
    plan: PlanSummary
    status: str
    billing_interval: str
    paddle_subscription_id: Optional[str] = None
    paddle_customer_id: Optional[str] = None
    current_period_end: Optional[str] = None
    scheduled_change: Optional[str] = None
    created_at: str
    updated_at: str


class SubscriptionListResponse(BaseModel):
    items: list[SubscriptionItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class CancelSubscriptionRequest(BaseModel):
    reason: Optional[str] = None


class CancelSubscriptionResponse(BaseModel):
    id: str
    status: str
    message: str


class ChangePlanRequest(BaseModel):
    plan_slug: str


class ChangePlanResponse(BaseModel):
    id: str
    old_plan: str
    new_plan: str
    status: str
    message: str


class RevenueByPlan(BaseModel):
    plan_name: str
    plan_slug: str
    active_subs: int
    monthly_revenue: float
    yearly_revenue: float


class RevenueResponse(BaseModel):
    mrr: float
    arr: float
    total_active_subscriptions: int
    new_subscriptions_this_month: int
    churn_rate: float
    by_plan: list[RevenueByPlan]


@router.get("/subscriptions", response_model=SubscriptionListResponse)
async def list_subscriptions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    query = select(Subscription).options(
        joinedload(Subscription.user),
        joinedload(Subscription.plan),
    )
    count_query = select(func.count(Subscription.id))

    if status:
        statuses = [s.strip() for s in status.split(",")]
        query = query.where(Subscription.status.in_(statuses))
        count_query = count_query.where(Subscription.status.in_(statuses))

    total_result = await session.execute(count_query)
    total = total_result.scalar_one()

    skip = (page - 1) * page_size
    query = query.order_by(Subscription.created_at.desc()).offset(skip).limit(page_size)
    result = await session.execute(query)
    subscriptions = list(result.unique().scalars().all())

    total_pages = max(1, (total + page_size - 1) // page_size)

    items = []
    for sub in subscriptions:
        sub_user = sub.user
        sub_plan = sub.plan
        items.append(
            SubscriptionItem(
                id=str(sub.id),
                user=UserSummary(
                    id=str(sub_user.id) if sub_user else "",
                    email=sub_user.email if sub_user else "unknown",
                    full_name=sub_user.full_name if sub_user else None,
                ),
                plan=PlanSummary(
                    id=str(sub_plan.id) if sub_plan else "",
                    name=sub_plan.name if sub_plan else "Unknown",
                    slug=sub_plan.slug if sub_plan else "unknown",
                    price_monthly=sub_plan.price_monthly if sub_plan else 0,
                    price_yearly=sub_plan.price_yearly if sub_plan else 0,
                ),
                status=sub.status,
                billing_interval=sub.billing_interval,
                paddle_subscription_id=sub.paddle_subscription_id,
                paddle_customer_id=sub.paddle_customer_id,
                current_period_end=sub.current_period_end.isoformat() if sub.current_period_end else None,
                scheduled_change=sub.scheduled_change,
                created_at=sub.created_at.isoformat(),
                updated_at=sub.updated_at.isoformat(),
            )
        )

    return SubscriptionListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.patch("/subscriptions/{subscription_id}/cancel", response_model=CancelSubscriptionResponse)
async def cancel_subscription_admin(
    subscription_id: uuid.UUID,
    req: CancelSubscriptionRequest = None,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    repo = SubscriptionRepository(session)
    sub = await repo.get_by_id(subscription_id)
    if not sub:
        raise NotFoundException(message="Subscription not found")

    if sub.paddle_subscription_id:
        try:
            await paddle_cancel(sub.paddle_subscription_id)
        except Exception as e:
            raise BadRequestException(
                message="Failed to cancel in Paddle",
                detail={"error": str(e)},
            )

    await repo.cancel(subscription_id)

    return CancelSubscriptionResponse(
        id=str(subscription_id),
        status="canceled",
        message="Subscription canceled successfully",
    )


@router.patch("/subscriptions/{subscription_id}/change-plan", response_model=ChangePlanResponse)
async def change_plan_admin(
    subscription_id: uuid.UUID,
    req: ChangePlanRequest,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    sub_repo = SubscriptionRepository(session)
    plan_repo = PlanRepository(session)

    sub = await sub_repo.get_by_id(subscription_id)
    if not sub:
        raise NotFoundException(message="Subscription not found")

    new_plan = await plan_repo.get_by_slug(req.plan_slug)
    if not new_plan:
        raise NotFoundException(message=f"Plan '{req.plan_slug}' not found")

    old_plan = await plan_repo.get_by_id(sub.plan_id)
    old_plan_name = old_plan.name if old_plan else "Unknown"

    await sub_repo.change_plan(subscription_id, new_plan.id)

    return ChangePlanResponse(
        id=str(subscription_id),
        old_plan=old_plan_name,
        new_plan=new_plan.name,
        status=sub.status,
        message="Plan changed successfully",
    )


@router.get("/revenue", response_model=RevenueResponse)
async def get_revenue(
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    admin_repo = AdminRepository(session)
    revenue = await admin_repo.get_revenue_stats()

    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    plan_stats = await session.execute(
        select(
            Plan.name,
            Plan.slug,
            Plan.price_monthly,
            Plan.price_yearly,
            func.count(Subscription.id).label("sub_count"),
        )
        .select_from(Subscription)
        .join(Plan, Subscription.plan_id == Plan.id)
        .where(Subscription.status.in_(["active", "trialing"]))
        .group_by(Plan.id, Plan.name, Plan.slug, Plan.price_monthly, Plan.price_yearly)
    )

    by_plan = []
    total_mrr = 0.0
    total_arr = 0.0

    for row in plan_stats:
        name, slug, price_monthly, price_yearly, sub_count = row
        plan_mrr = price_monthly * sub_count
        plan_arr = price_yearly * sub_count
        total_mrr += plan_mrr
        total_arr += plan_arr

        by_plan.append(
            RevenueByPlan(
                plan_name=name,
                plan_slug=slug,
                active_subs=sub_count,
                monthly_revenue=round(plan_mrr, 2),
                yearly_revenue=round(plan_arr, 2),
            )
        )

    total_subs = await session.execute(
        select(func.count(Subscription.id))
    )
    total_sub_count = total_subs.scalar_one()
    churn_rate = 0.0
    if total_sub_count > 0:
        canceled_this_month = await session.execute(
            select(func.count(Subscription.id)).where(
                Subscription.status == "canceled",
                Subscription.cancelled_at >= month_start,
            )
        )
        canceled = canceled_this_month.scalar_one()
        churn_rate = round(canceled / total_sub_count * 100, 2) if total_sub_count > 0 else 0.0

    return RevenueResponse(
        mrr=round(total_mrr, 2),
        arr=round(total_arr, 2),
        total_active_subscriptions=revenue["total_active_subscriptions"],
        new_subscriptions_this_month=revenue["new_subscriptions_this_month"],
        churn_rate=churn_rate,
        by_plan=by_plan,
    )
