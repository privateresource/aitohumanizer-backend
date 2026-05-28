import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_admin_user
from app.core.exceptions import BadRequestException, NotFoundException
from app.core.constants import PLAN_LIMITS
from app.db.models.user import User
from app.db.models.word_usage import WordUsage
from app.db.repositories.user_repo import UserRepository
from app.db.repositories.word_usage_repo import WordUsageRepository
from app.db.repositories.subscription_repo import SubscriptionRepository
from app.db.repositories.plan_repo import PlanRepository
from app.db.repositories.humanize_repo import HumanizeRepository

router = APIRouter(prefix="/admin/users", tags=["admin"])


class WordAdjustment(BaseModel):
    words: int
    description: str


class AdminUserResponse(BaseModel):
    id: str
    email: str
    full_name: Optional[str] = None
    role: str
    is_active: bool
    is_email_verified: bool
    avatar_url: Optional[str] = None
    last_login_at: Optional[str] = None
    created_at: str
    updated_at: str


class AdminUserDetailResponse(AdminUserResponse):
    words_remaining: int
    words_per_month: int
    words_used_this_month: int
    subscription_plan: Optional[str] = None
    subscription_status: Optional[str] = None
    total_requests: int
    paddle_customer_id: Optional[str] = None


class AdminUserListResponse(BaseModel):
    items: list[AdminUserResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class AdminUserUpdateRequest(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None
    full_name: Optional[str] = None


class WordAdjustmentResponse(BaseModel):
    id: str
    words: int
    description: str
    words_remaining: int
    created_at: str


class SuspendResponse(BaseModel):
    message: str
    user_id: str
    is_active: bool


class DeleteResponse(BaseModel):
    message: str
    user_id: str


@router.get("", response_model=AdminUserListResponse)
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    role: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    repo = UserRepository(session)
    skip = (page - 1) * page_size
    users, total = await repo.list(
        skip=skip,
        limit=page_size,
        role=role,
        is_active=is_active,
        search=search,
    )

    total_pages = max(1, (total + page_size - 1) // page_size)

    items = [
        AdminUserResponse(
            id=str(u.id),
            email=u.email,
            full_name=u.full_name,
            role=u.role,
            is_active=u.is_active,
            is_email_verified=u.is_email_verified,
            avatar_url=u.avatar_url,
            last_login_at=u.last_login_at.isoformat() if u.last_login_at else None,
            created_at=u.created_at.isoformat(),
            updated_at=u.updated_at.isoformat(),
        )
        for u in users
    ]

    return AdminUserListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/{user_id}", response_model=AdminUserDetailResponse)
async def get_user_detail(
    user_id: uuid.UUID,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    repo = UserRepository(session)
    user = await repo.get_by_id(user_id)
    if not user:
        raise NotFoundException(message="User not found")

    word_repo = WordUsageRepository(session)
    sub_repo = SubscriptionRepository(session)
    plan_repo = PlanRepository(session)
    humanize_repo = HumanizeRepository(session)

    subscription = await sub_repo.get_by_user(user_id)
    plan_slug = "free"
    plan = None
    words_per_month = 500

    if subscription:
        plan = await plan_repo.get_by_id(subscription.plan_id)
        if plan:
            plan_slug = plan.slug
            words_per_month = plan.words_per_month

    if plan:
        limits = {"words_per_month": plan.words_per_month}
    else:
        limits = PLAN_LIMITS.get(plan_slug, {"words_per_month": 500})

    words_per_month = limits.get("words_per_month", 500)
    words_remaining = await word_repo.get_balance(user_id, words_per_month)

    if words_per_month == -1:
        words_used = 0
    else:
        words_used = words_per_month - words_remaining

    stats = await humanize_repo.get_stats(user_id)

    return AdminUserDetailResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        is_email_verified=user.is_email_verified,
        avatar_url=user.avatar_url,
        last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
        created_at=user.created_at.isoformat(),
        updated_at=user.updated_at.isoformat(),
        words_remaining=words_remaining,
        words_per_month=words_per_month,
        words_used_this_month=words_used,
        subscription_plan=plan_slug,
        subscription_status=subscription.status if subscription else None,
        total_requests=stats["total_requests"],
        paddle_customer_id=subscription.paddle_customer_id if subscription else None,
    )


@router.patch("/{user_id}", response_model=AdminUserResponse)
async def update_user(
    user_id: uuid.UUID,
    req: AdminUserUpdateRequest,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    repo = UserRepository(session)
    user = await repo.get_by_id(user_id)
    if not user:
        raise NotFoundException(message="User not found")

    update_data = {}
    if req.role is not None:
        from app.core.constants import ROLE_HIERARCHY
        if req.role not in ROLE_HIERARCHY:
            raise BadRequestException(
                message=f"Invalid role. Must be one of: {', '.join(ROLE_HIERARCHY.keys())}"
            )
        update_data["role"] = req.role
    if req.is_active is not None:
        update_data["is_active"] = req.is_active
    if req.full_name is not None:
        update_data["full_name"] = req.full_name

    if not update_data:
        raise BadRequestException(message="No fields to update")

    updated = await repo.update(user_id, update_data)
    if not updated:
        raise NotFoundException(message="User not found")

    return AdminUserResponse(
        id=str(updated.id),
        email=updated.email,
        full_name=updated.full_name,
        role=updated.role,
        is_active=updated.is_active,
        is_email_verified=updated.is_email_verified,
        avatar_url=updated.avatar_url,
        last_login_at=updated.last_login_at.isoformat() if updated.last_login_at else None,
        created_at=updated.created_at.isoformat(),
        updated_at=updated.updated_at.isoformat(),
    )


@router.post("/{user_id}/words", response_model=WordAdjustmentResponse)
async def adjust_words(
    user_id: uuid.UUID,
    req: WordAdjustment,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    repo = UserRepository(session)
    user = await repo.get_by_id(user_id)
    if not user:
        raise NotFoundException(message="User not found")

    word_repo = WordUsageRepository(session)

    now = datetime.now(timezone.utc)
    period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    if req.words > 0:
        entry = WordUsage(
            user_id=user_id,
            words_used=req.words,
            mode="standard",
            source="admin_adjustment",
            request_id=None,
            period_start=period_start,
            description=req.description,
        )
    else:
        entry = WordUsage(
            user_id=user_id,
            words_used=req.words,
            mode="standard",
            source="admin_adjustment",
            request_id=None,
            period_start=period_start,
            description=req.description,
        )

    await word_repo.add_entry(entry)

    from app.core.constants import PLAN_LIMITS
    sub_repo = SubscriptionRepository(session)
    plan_repo = PlanRepository(session)
    subscription = await sub_repo.get_by_user(user_id)
    words_per_month = 500
    if subscription:
        plan = await plan_repo.get_by_id(subscription.plan_id)
        if plan:
            words_per_month = plan.words_per_month
    else:
        words_per_month = PLAN_LIMITS.get("free", {}).get("words_per_month", 500)

    words_remaining = await word_repo.get_balance(user_id, words_per_month)

    return WordAdjustmentResponse(
        id=str(entry.id),
        words=req.words,
        description=req.description,
        words_remaining=words_remaining,
        created_at=entry.created_at.isoformat(),
    )


@router.post("/{user_id}/suspend", response_model=SuspendResponse)
async def suspend_user(
    user_id: uuid.UUID,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    if current_user.id == user_id:
        raise BadRequestException(message="Cannot suspend yourself")

    repo = UserRepository(session)
    user = await repo.get_by_id(user_id)
    if not user:
        raise NotFoundException(message="User not found")

    updated = await repo.update(user_id, {"is_active": False})
    return SuspendResponse(
        message="User suspended successfully",
        user_id=str(user_id),
        is_active=False,
    )


@router.post("/{user_id}/activate", response_model=SuspendResponse)
async def activate_user(
    user_id: uuid.UUID,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    repo = UserRepository(session)
    user = await repo.get_by_id(user_id)
    if not user:
        raise NotFoundException(message="User not found")

    updated = await repo.update(user_id, {"is_active": True})
    return SuspendResponse(
        message="User activated successfully",
        user_id=str(user_id),
        is_active=True,
    )


@router.delete("/{user_id}", response_model=DeleteResponse)
async def delete_user(
    user_id: uuid.UUID,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    if current_user.id == user_id:
        raise BadRequestException(message="Cannot delete yourself")

    repo = UserRepository(session)
    user = await repo.get_by_id(user_id)
    if not user:
        raise NotFoundException(message="User not found")

    await repo.soft_delete(user_id)

    anonymized_email = f"deleted-{user_id}@anon.aitohumanizer.com"
    await repo.update(user_id, {
        "email": anonymized_email,
        "full_name": "Deleted User",
        "avatar_url": None,
    })

    return DeleteResponse(
        message="User soft deleted (GDPR compliant)",
        user_id=str(user_id),
    )
