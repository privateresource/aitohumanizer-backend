from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.core.exceptions import BadRequestException, NotFoundException
from app.core.constants import PLAN_LIMITS
from app.db.models.user import User
from app.db.repositories.user_repo import UserRepository
from app.db.repositories.humanize_repo import HumanizeRepository
from app.db.repositories.subscription_repo import SubscriptionRepository
from app.db.repositories.plan_repo import PlanRepository
from app.db.repositories.word_usage_repo import WordUsageRepository

router = APIRouter(prefix="/users", tags=["users"])


class PlanDetail(BaseModel):
    id: str
    name: str
    slug: str
    words_per_month: int
    words_per_request: int
    modes: list[str]
    price_monthly: float
    price_yearly: float
    is_featured: bool


class SubscriptionDetail(BaseModel):
    id: str
    plan: PlanDetail
    status: str
    billing_interval: str
    current_period_start: Optional[str] = None
    current_period_end: Optional[str] = None
    scheduled_change: Optional[str] = None
    paddle_subscription_id: Optional[str] = None
    created_at: str


class QuotaDetail(BaseModel):
    words_remaining: int
    words_per_month: int
    words_used_this_month: int
    quota_pct_remaining: float
    quota_urgency: str


class UserProfileResponse(BaseModel):
    id: str
    email: str
    full_name: Optional[str] = None
    role: str
    is_active: bool
    is_email_verified: bool
    avatar_url: Optional[str] = None
    quota: QuotaDetail
    subscription: Optional[SubscriptionDetail] = None
    created_at: str
    updated_at: str


class UpdateProfileRequest(BaseModel):
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None


class UpdateProfileResponse(BaseModel):
    id: str
    email: str
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    updated_at: str


class HistoryItem(BaseModel):
    id: str
    input_text: str
    output_text: Optional[str] = None
    mode: str
    word_count: int
    processing_time_ms: Optional[int] = None
    ai_model: Optional[str] = None
    created_at: str


class HistoryResponse(BaseModel):
    items: list[HistoryItem]
    total: int
    page: int
    page_size: int
    total_pages: int


@router.get("/me", response_model=UserProfileResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    plan = None
    plan_slug = "free"

    sub_repo = SubscriptionRepository(session)
    subscription = await sub_repo.get_by_user(current_user.id)

    if subscription:
        plan_repo = PlanRepository(session)
        plan = await plan_repo.get_by_id(subscription.plan_id)
        if plan:
            plan_slug = plan.slug

    if plan:
        limits = {
            "words_per_month": plan.words_per_month,
            "words_per_request": plan.words_per_request,
            "modes": plan.modes or [],
        }
    else:
        limits = PLAN_LIMITS.get(plan_slug, {})

    words_per_month = limits.get("words_per_month", 500)
    word_repo = WordUsageRepository(session)
    words_remaining = await word_repo.get_balance(current_user.id, words_per_month)

    if words_per_month == -1:
        words_used = 0
        quota_pct = 100.0
    else:
        words_used = words_per_month - words_remaining
        quota_pct = (words_remaining / words_per_month * 100) if words_per_month > 0 else 0

    if quota_pct > 50:
        urgency = "good"
    elif quota_pct > 20:
        urgency = "low"
    elif quota_pct > 10:
        urgency = "medium"
    else:
        urgency = "critical"

    sub_detail = None
    if subscription and plan:
        sub_detail = SubscriptionDetail(
            id=str(subscription.id),
            plan=PlanDetail(
                id=str(plan.id),
                name=plan.name,
                slug=plan.slug,
                words_per_month=plan.words_per_month,
                words_per_request=plan.words_per_request,
                modes=plan.modes or [],
                price_monthly=plan.price_monthly,
                price_yearly=plan.price_yearly,
                is_featured=plan.is_featured,
            ),
            status=subscription.status,
            billing_interval=subscription.billing_interval,
            current_period_start=subscription.current_period_start.isoformat() if subscription.current_period_start else None,
            current_period_end=subscription.current_period_end.isoformat() if subscription.current_period_end else None,
            scheduled_change=subscription.scheduled_change,
            paddle_subscription_id=subscription.paddle_subscription_id,
            created_at=subscription.created_at.isoformat(),
        )

    return UserProfileResponse(
        id=str(current_user.id),
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role,
        is_active=current_user.is_active,
        is_email_verified=current_user.is_email_verified,
        avatar_url=current_user.avatar_url,
        quota=QuotaDetail(
            words_remaining=words_remaining,
            words_per_month=words_per_month,
            words_used_this_month=words_used,
            quota_pct_remaining=round(quota_pct, 1),
            quota_urgency=urgency,
        ),
        subscription=sub_detail,
        created_at=current_user.created_at.isoformat(),
        updated_at=current_user.updated_at.isoformat(),
    )


@router.patch("/me", response_model=UpdateProfileResponse)
async def update_me(
    req: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    update_data = {}
    if req.full_name is not None:
        update_data["full_name"] = req.full_name
    if req.avatar_url is not None:
        update_data["avatar_url"] = req.avatar_url

    if not update_data:
        raise BadRequestException(message="No fields to update")

    repo = UserRepository(session)
    updated = await repo.update(current_user.id, update_data)
    if not updated:
        raise NotFoundException(message="User not found")

    return UpdateProfileResponse(
        id=str(updated.id),
        email=updated.email,
        full_name=updated.full_name,
        avatar_url=updated.avatar_url,
        updated_at=updated.updated_at.isoformat(),
    )


@router.get("/me/history", response_model=HistoryResponse)
async def get_history(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    mode: Optional[str] = Query(None, description="Filter by mode"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    skip = (page - 1) * page_size
    repo = HumanizeRepository(session)
    requests, total = await repo.get_by_user(
        current_user.id,
        skip=skip,
        limit=page_size,
        mode=mode,
    )

    total_pages = max(1, (total + page_size - 1) // page_size)

    items = [
        HistoryItem(
            id=str(r.id),
            input_text=r.input_text[:500] if r.input_text else "",
            output_text=r.output_text[:500] if r.output_text else None,
            mode=r.mode,
            word_count=r.word_count,
            processing_time_ms=r.processing_time_ms,
            ai_model=r.ai_model,
            created_at=r.created_at.isoformat(),
        )
        for r in requests
    ]

    return HistoryResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
