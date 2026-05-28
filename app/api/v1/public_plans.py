from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.cache import cache
from app.cache.cache_keys import PUBLIC_PLANS_KEY

router = APIRouter(prefix="/plans", tags=["plans"])


class PublicFeature(BaseModel):
    feature_key: str
    feature_value: str


class PublicToolLimit(BaseModel):
    tool: str
    max_requests_per_month: int
    max_requests_per_day: int
    max_words_per_request: int


class PublicPlanResponse(BaseModel):
    id: int
    name: str
    slug: str
    description: Optional[str] = None
    tagline: Optional[str] = None
    monthly_price_usd: float
    annual_price_usd: float
    original_price_usd: Optional[float] = None
    badge_text: Optional[str] = None
    display_order: int
    is_featured: bool
    is_free: bool
    max_words_per_month: int = -1
    tool_limits: list[PublicToolLimit]
    features: list[PublicFeature]


@router.get("/public", response_model=list[PublicPlanResponse])
async def list_public_plans():
    plans = await cache.get_or_load(PUBLIC_PLANS_KEY)
    if plans is None:
        return []
    return [PublicPlanResponse(**p) for p in plans]
