from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.db.repositories.plan_repo import PlanRepository

router = APIRouter(prefix="/plans", tags=["plans"])


class PlanResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: str | None = None
    price_monthly: float
    price_yearly: float
    words_per_month: int
    words_per_request: int
    modes: list[str]
    is_featured: bool
    sort_order: int


@router.get("", response_model=list[PlanResponse])
async def list_plans(
    session: AsyncSession = Depends(get_db_session),
):
    repo = PlanRepository(session)
    plans = await repo.get_all_active()
    return [
        PlanResponse(
            id=str(p.id),
            name=p.name,
            slug=p.slug,
            description=p.description,
            price_monthly=p.price_monthly,
            price_yearly=p.price_yearly,
            words_per_month=p.words_per_month,
            words_per_request=p.words_per_request,
            modes=p.modes or [],
            is_featured=p.is_featured,
            sort_order=p.sort_order,
        )
        for p in plans
    ]
