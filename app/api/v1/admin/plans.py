import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_admin_user
from app.core.exceptions import BadRequestException, NotFoundException
from app.db.models.user import User
from app.db.models.plan import Plan
from app.db.repositories.plan_repo import PlanRepository
from app.billing.paddle_client import create_product, create_price

router = APIRouter(prefix="/admin/plans", tags=["admin"])


class PlanResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: Optional[str] = None
    price_monthly: float
    price_yearly: float
    paddle_price_id_monthly: Optional[str] = None
    paddle_price_id_yearly: Optional[str] = None
    paddle_product_id: Optional[str] = None
    words_per_month: int
    words_per_request: int
    modes: list[str]
    is_active: bool
    sort_order: int
    is_featured: bool
    created_at: str
    updated_at: str


class PlanCreateRequest(BaseModel):
    name: str
    slug: str
    description: Optional[str] = None
    price_monthly: float = 0
    price_yearly: float = 0
    words_per_month: int = 500
    words_per_request: int = 200
    modes: list[str] = ["standard"]
    sort_order: int = 0
    is_featured: bool = False


class PlanUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price_monthly: Optional[float] = None
    price_yearly: Optional[float] = None
    words_per_month: Optional[int] = None
    words_per_request: Optional[int] = None
    modes: Optional[list[str]] = None
    sort_order: Optional[int] = None
    is_featured: Optional[bool] = None


class DeleteResponse(BaseModel):
    status: str
    message: str
    id: str


@router.get("", response_model=list[PlanResponse])
async def list_plans(
    include_inactive: bool = Query(False),
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    repo = PlanRepository(session)
    if include_inactive:
        from sqlalchemy import select
        result = await session.execute(
            select(Plan).order_by(Plan.sort_order.asc())
        )
        plans = list(result.scalars().all())
    else:
        plans = await repo.get_all_active()

    return [
        PlanResponse(
            id=str(p.id),
            name=p.name,
            slug=p.slug,
            description=p.description,
            price_monthly=p.price_monthly,
            price_yearly=p.price_yearly,
            paddle_price_id_monthly=p.paddle_price_id_monthly,
            paddle_price_id_yearly=p.paddle_price_id_yearly,
            paddle_product_id=p.paddle_product_id,
            words_per_month=p.words_per_month,
            words_per_request=p.words_per_request,
            modes=p.modes or [],
            is_active=p.is_active,
            sort_order=p.sort_order,
            is_featured=p.is_featured,
            created_at=p.created_at.isoformat(),
            updated_at=p.updated_at.isoformat(),
        )
        for p in plans
    ]


@router.post("", response_model=PlanResponse, status_code=201)
async def create_plan(
    req: PlanCreateRequest,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    repo = PlanRepository(session)

    existing = await repo.get_by_slug(req.slug)
    if existing:
        raise BadRequestException(
            message=f"Plan with slug '{req.slug}' already exists",
            detail={"existing_plan_id": str(existing.id)},
        )

    if not req.modes:
        raise BadRequestException(message="At least one mode must be specified")

    paddle_product_id = None
    paddle_price_id_monthly = None
    paddle_price_id_yearly = None

    try:
        if req.price_monthly > 0 or req.price_yearly > 0:
            paddle_product_id = await create_product(
                name=req.name,
                description=req.description or f"{req.name} plan",
            )

            if paddle_product_id and req.price_monthly > 0:
                amount_cents = str(int(req.price_monthly * 100))
                paddle_price_id_monthly = await create_price(
                    product_id=paddle_product_id,
                    name=f"{req.name} Monthly",
                    amount=amount_cents,
                    interval="month",
                )

            if paddle_product_id and req.price_yearly > 0:
                amount_cents = str(int(req.price_yearly * 100))
                paddle_price_id_yearly = await create_price(
                    product_id=paddle_product_id,
                    name=f"{req.name} Yearly",
                    amount=amount_cents,
                    interval="year",
                )
    except Exception as e:
        pass

    now = datetime.now(timezone.utc)
    plan = Plan(
        name=req.name,
        slug=req.slug,
        description=req.description,
        price_monthly=req.price_monthly,
        price_yearly=req.price_yearly,
        paddle_price_id_monthly=paddle_price_id_monthly,
        paddle_price_id_yearly=paddle_price_id_yearly,
        paddle_product_id=paddle_product_id,
        words_per_month=req.words_per_month,
        words_per_request=req.words_per_request,
        modes=req.modes,
        is_active=True,
        sort_order=req.sort_order,
        is_featured=req.is_featured,
    )
    created = await repo.create(plan)

    return PlanResponse(
        id=str(created.id),
        name=created.name,
        slug=created.slug,
        description=created.description,
        price_monthly=created.price_monthly,
        price_yearly=created.price_yearly,
        paddle_price_id_monthly=created.paddle_price_id_monthly,
        paddle_price_id_yearly=created.paddle_price_id_yearly,
        paddle_product_id=created.paddle_product_id,
        words_per_month=created.words_per_month,
        words_per_request=created.words_per_request,
        modes=created.modes or [],
        is_active=created.is_active,
        sort_order=created.sort_order,
        is_featured=created.is_featured,
        created_at=created.created_at.isoformat(),
        updated_at=created.updated_at.isoformat(),
    )


@router.patch("/{plan_id}", response_model=PlanResponse)
async def update_plan(
    plan_id: uuid.UUID,
    req: PlanUpdateRequest,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    repo = PlanRepository(session)
    plan = await repo.get_by_id(plan_id)
    if not plan:
        raise NotFoundException(message="Plan not found")

    update_data = {}
    if req.name is not None:
        update_data["name"] = req.name
    if req.description is not None:
        update_data["description"] = req.description
    if req.price_monthly is not None:
        update_data["price_monthly"] = req.price_monthly
    if req.price_yearly is not None:
        update_data["price_yearly"] = req.price_yearly
    if req.words_per_month is not None:
        update_data["words_per_month"] = req.words_per_month
    if req.words_per_request is not None:
        update_data["words_per_request"] = req.words_per_request
    if req.modes is not None:
        update_data["modes"] = req.modes
    if req.sort_order is not None:
        update_data["sort_order"] = req.sort_order
    if req.is_featured is not None:
        update_data["is_featured"] = req.is_featured

    if not update_data:
        raise BadRequestException(message="No fields to update")

    if req.price_monthly is not None and req.price_monthly > 0 and plan.paddle_price_id_monthly is None:
        try:
            product_id = plan.paddle_product_id
            if not product_id:
                product_id = await create_product(name=plan.name, description=plan.description or "")
            if product_id:
                amount_cents = str(int(req.price_monthly * 100))
                new_price_id = await create_price(
                    product_id=product_id,
                    name=f"{plan.name} Monthly",
                    amount=amount_cents,
                    interval="month",
                )
                if new_price_id:
                    update_data["paddle_product_id"] = product_id
                    update_data["paddle_price_id_monthly"] = new_price_id
        except Exception:
            pass

    if req.price_yearly is not None and req.price_yearly > 0 and plan.paddle_price_id_yearly is None:
        try:
            product_id = update_data.get("paddle_product_id", plan.paddle_product_id)
            if not product_id:
                product_id = await create_product(name=plan.name, description=plan.description or "")
            if product_id:
                amount_cents = str(int(req.price_yearly * 100))
                new_price_id = await create_price(
                    product_id=product_id,
                    name=f"{plan.name} Yearly",
                    amount=amount_cents,
                    interval="year",
                )
                if new_price_id:
                    update_data["paddle_product_id"] = product_id
                    update_data["paddle_price_id_yearly"] = new_price_id
        except Exception:
            pass

    updated = await repo.update(plan_id, update_data)
    if not updated:
        raise NotFoundException(message="Plan not found")

    return PlanResponse(
        id=str(updated.id),
        name=updated.name,
        slug=updated.slug,
        description=updated.description,
        price_monthly=updated.price_monthly,
        price_yearly=updated.price_yearly,
        paddle_price_id_monthly=updated.paddle_price_id_monthly,
        paddle_price_id_yearly=updated.paddle_price_id_yearly,
        paddle_product_id=updated.paddle_product_id,
        words_per_month=updated.words_per_month,
        words_per_request=updated.words_per_request,
        modes=updated.modes or [],
        is_active=updated.is_active,
        sort_order=updated.sort_order,
        is_featured=updated.is_featured,
        created_at=updated.created_at.isoformat(),
        updated_at=updated.updated_at.isoformat(),
    )


@router.delete("/{plan_id}", response_model=DeleteResponse)
async def deactivate_plan(
    plan_id: uuid.UUID,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    repo = PlanRepository(session)
    plan = await repo.get_by_id(plan_id)
    if not plan:
        raise NotFoundException(message="Plan not found")

    await repo.deactivate(plan_id)

    return DeleteResponse(
        status="deactivated",
        message=f"Plan '{plan.name}' has been deactivated",
        id=str(plan_id),
    )
