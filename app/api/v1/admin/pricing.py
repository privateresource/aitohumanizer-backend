from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_admin_user
from app.cache.invalidation import invalidate_all, invalidate_coupons
from app.core.exceptions import BadRequestException, NotFoundException
from app.db.models.user import User
from app.pricing.usage import get_plan_tool_limits, get_plan_features

router = APIRouter(prefix="/admin/pricing", tags=["admin"])


class PricingPlanResponse(BaseModel):
    id: int
    name: str
    slug: str
    description: Optional[str] = None
    tagline: Optional[str] = None
    monthly_price_usd: float
    annual_price_usd: float
    original_price_usd: Optional[float] = None
    paddle_monthly_price_id: Optional[str] = None
    paddle_annual_price_id: Optional[str] = None
    badge_text: Optional[str] = None
    display_order: int
    is_active: bool
    is_featured: bool
    is_public: bool
    is_free: bool
    max_words_per_month: int = -1
    tool_limits: list[dict] = []
    features: list[dict] = []
    created_at: str
    updated_at: str


class PricingPlanCreate(BaseModel):
    name: str
    slug: str
    description: Optional[str] = None
    tagline: Optional[str] = None
    monthly_price_usd: float = 0
    annual_price_usd: float = 0
    original_price_usd: Optional[float] = None
    badge_text: Optional[str] = None
    display_order: int = 99
    is_featured: bool = False
    is_public: bool = True
    is_free: bool = False
    max_words_per_month: int = -1


class PricingPlanUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tagline: Optional[str] = None
    monthly_price_usd: Optional[float] = None
    annual_price_usd: Optional[float] = None
    original_price_usd: Optional[float] = None
    badge_text: Optional[str] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None
    is_featured: Optional[bool] = None
    is_public: Optional[bool] = None
    is_free: Optional[bool] = None
    max_words_per_month: Optional[int] = None


class ToolLimitResponse(BaseModel):
    id: int
    tool: str
    max_requests_per_month: int
    max_requests_per_day: int
    max_words_per_request: int
    enabled: bool


class ToolLimitUpdate(BaseModel):
    max_requests_per_month: Optional[int] = None
    max_requests_per_day: Optional[int] = None
    max_words_per_request: Optional[int] = None
    enabled: Optional[bool] = None


class FeatureResponse(BaseModel):
    id: int
    feature_key: str
    feature_value: str
    sort_order: int = 0


class FeatureCreate(BaseModel):
    feature_key: str
    feature_value: str = "true"
    sort_order: int = 0


class UsageStatsResponse(BaseModel):
    user_id: str
    tool: str
    requests_used: int
    words_used: int
    period_start: str
    period_end: str


async def _get_plan_or_404(session: AsyncSession, plan_id: int) -> dict:
    result = await session.execute(
        text("SELECT * FROM pricing_plans WHERE id = :id"),
        {"id": plan_id},
    )
    row = result.fetchone()
    if not row:
        raise NotFoundException(message="Pricing plan not found")
    return row


def _row_to_plan_response(row, limits=None, features=None) -> PricingPlanResponse:
    return PricingPlanResponse(
        id=row.id,
        name=row.name,
        slug=row.slug,
        description=row.description,
        tagline=row.tagline,
        monthly_price_usd=float(row.monthly_price_usd) if row.monthly_price_usd else 0,
        annual_price_usd=float(row.annual_price_usd) if row.annual_price_usd else 0,
        original_price_usd=float(row.original_price_usd) if row.original_price_usd else None,
        paddle_monthly_price_id=row.paddle_monthly_price_id,
        paddle_annual_price_id=row.paddle_annual_price_id,
        badge_text=row.badge_text,
        display_order=row.display_order,
        is_active=row.is_active,
        is_featured=row.is_featured,
        is_public=row.is_public,
        is_free=row.is_free,
        max_words_per_month=row.max_words_per_month if hasattr(row, 'max_words_per_month') and row.max_words_per_month is not None else -1,
        tool_limits=limits or [],
        features=features or [],
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.get("/plans", response_model=list[PricingPlanResponse])
async def list_pricing_plans(
    include_inactive: bool = False,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    query = "SELECT * FROM pricing_plans"
    if not include_inactive:
        query += " WHERE is_active = true"
    query += " ORDER BY display_order ASC"

    result = await session.execute(text(query))
    rows = result.fetchall()

    plans = []
    for row in rows:
        limits = await get_plan_tool_limits(session, row.id)
        features = await get_plan_features(session, row.id)
        plans.append(_row_to_plan_response(row, limits, features))
    return plans


@router.get("/plans/{plan_id}", response_model=PricingPlanResponse)
async def get_pricing_plan(
    plan_id: int,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    row = await _get_plan_or_404(session, plan_id)
    limits = await get_plan_tool_limits(session, plan_id)
    features = await get_plan_features(session, plan_id)
    return _row_to_plan_response(row, limits, features)


@router.post("/plans", response_model=PricingPlanResponse, status_code=201)
async def create_pricing_plan(
    req: PricingPlanCreate,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    existing = await session.execute(
        text("SELECT id FROM pricing_plans WHERE slug = :slug"),
        {"slug": req.slug},
    )
    if existing.fetchone():
        raise BadRequestException(message=f"Plan with slug '{req.slug}' already exists")

    now = datetime.now(timezone.utc)
    result = await session.execute(
        text("""
            INSERT INTO pricing_plans (name, slug, description, tagline, monthly_price_usd, annual_price_usd, original_price_usd, badge_text, display_order, is_featured, is_public, is_free, max_words_per_month, created_at, updated_at)
            VALUES (:name, :slug, :desc, :tagline, :monthly, :annual, :original, :badge, :order, :featured, :public, :free, :max_words, :now, :now)
            RETURNING *
        """),
        {
            "name": req.name, "slug": req.slug, "desc": req.description,
            "tagline": req.tagline, "monthly": req.monthly_price_usd,
            "annual": req.annual_price_usd, "original": req.original_price_usd,
            "badge": req.badge_text, "order": req.display_order,
            "featured": req.is_featured, "public": req.is_public,
            "free": req.is_free, "max_words": req.max_words_per_month, "now": now,
        },
    )
    await session.commit()
    row = result.fetchone()

    await invalidate_all()
    return _row_to_plan_response(row)


@router.patch("/plans/{plan_id}", response_model=PricingPlanResponse)
async def update_pricing_plan(
    plan_id: int,
    req: PricingPlanUpdate,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _get_plan_or_404(session, plan_id)

    updates = []
    params = {"id": plan_id}

    for field in ("name", "description", "tagline", "badge_text", "display_order", "is_active", "is_featured", "is_public", "is_free"):
        val = getattr(req, field, None)
        if val is not None:
            col = field
            updates.append(f"{col} = :{col}")
            params[col] = val

    for field, col in [("monthly_price_usd", "monthly_price_usd"), ("annual_price_usd", "annual_price_usd"), ("original_price_usd", "original_price_usd"), ("max_words_per_month", "max_words_per_month")]:
        val = getattr(req, field, None)
        if val is not None:
            updates.append(f"{col} = :{col}")
            params[col] = val

    if not updates:
        raise BadRequestException(message="No fields to update")

    updates.append("updated_at = :now")
    params["now"] = datetime.now(timezone.utc)

    await session.execute(
        text(f"UPDATE pricing_plans SET {', '.join(updates)} WHERE id = :id"),
        params,
    )
    await session.commit()
    await invalidate_all()

    row = await _get_plan_or_404(session, plan_id)
    limits = await get_plan_tool_limits(session, plan_id)
    features = await get_plan_features(session, plan_id)
    return _row_to_plan_response(row, limits, features)


@router.delete("/plans/{plan_id}")
async def delete_pricing_plan(
    plan_id: int,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _get_plan_or_404(session, plan_id)
    await session.execute(
        text("DELETE FROM pricing_plans WHERE id = :id"),
        {"id": plan_id},
    )
    await session.commit()
    await invalidate_all()
    return {"status": "deleted", "id": plan_id}


TOOLS_LIST = ["humanize", "paraphrase", "grammar_check", "ai_detector"]


@router.get("/plans/{plan_id}/limits", response_model=list[ToolLimitResponse])
async def list_plan_limits(
    plan_id: int,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _get_plan_or_404(session, plan_id)
    existing = await get_plan_tool_limits(session, plan_id)
    existing_tools = {l["tool"] for l in existing}

    now = datetime.now(timezone.utc)
    for tool in TOOLS_LIST:
        if tool not in existing_tools:
            await session.execute(
                text("""
                    INSERT INTO plan_tool_limits (plan_id, tool, max_requests_per_month, max_requests_per_day, max_words_per_request, enabled, created_at, updated_at)
                    VALUES (:pid, :tool, -1, -1, 3000, true, :now, :now)
                    ON CONFLICT (plan_id, tool) DO NOTHING
                """),
                {"pid": plan_id, "tool": tool, "now": now},
            )
    if len(existing) < len(TOOLS_LIST):
        await session.commit()

    result = await session.execute(
        text("SELECT * FROM plan_tool_limits WHERE plan_id = :pid ORDER BY tool"),
        {"pid": plan_id},
    )
    return [
        ToolLimitResponse(
            id=r.id,
            tool=r.tool,
            max_requests_per_month=r.max_requests_per_month,
            max_requests_per_day=r.max_requests_per_day,
            max_words_per_request=r.max_words_per_request,
            enabled=r.enabled,
        )
        for r in result.fetchall()
    ]


@router.patch("/plans/{plan_id}/limits/{limit_id}", response_model=ToolLimitResponse)
async def update_plan_limit(
    plan_id: int,
    limit_id: int,
    req: ToolLimitUpdate,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _get_plan_or_404(session, plan_id)

    updates = []
    params = {"id": limit_id, "pid": plan_id}

    for field in ("max_requests_per_month", "max_requests_per_day", "max_words_per_request", "enabled"):
        val = getattr(req, field, None)
        if val is not None:
            updates.append(f"{field} = :{field}")
            params[field] = val

    if not updates:
        raise BadRequestException(message="No fields to update")

    updates.append("updated_at = :now")
    params["now"] = datetime.now(timezone.utc)

    await session.execute(
        text(f"UPDATE plan_tool_limits SET {', '.join(updates)} WHERE id = :id AND plan_id = :pid"),
        params,
    )
    await session.commit()
    await invalidate_all()

    result = await session.execute(
        text("SELECT * FROM plan_tool_limits WHERE id = :id"),
        {"id": limit_id},
    )
    r = result.fetchone()
    if not r:
        raise NotFoundException(message="Tool limit not found")
    return ToolLimitResponse(
        id=r.id, tool=r.tool,
        max_requests_per_month=r.max_requests_per_month,
        max_requests_per_day=r.max_requests_per_day,
        max_words_per_request=r.max_words_per_request,
        enabled=r.enabled,
    )


@router.get("/plans/{plan_id}/features", response_model=list[FeatureResponse])
async def list_plan_features(
    plan_id: int,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _get_plan_or_404(session, plan_id)
    result = await session.execute(
        text("SELECT * FROM plan_features WHERE plan_id = :pid ORDER BY sort_order ASC, feature_key ASC"),
        {"pid": plan_id},
    )
    return [
        FeatureResponse(id=r.id, feature_key=r.feature_key, feature_value=r.feature_value, sort_order=r.sort_order)
        for r in result.fetchall()
    ]


@router.post("/plans/{plan_id}/features", response_model=FeatureResponse, status_code=201)
async def create_plan_feature(
    plan_id: int,
    req: FeatureCreate,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _get_plan_or_404(session, plan_id)
    now = datetime.now(timezone.utc)
    result = await session.execute(
        text("""
            INSERT INTO plan_features (plan_id, feature_key, feature_value, sort_order, created_at)
            VALUES (:pid, :key, :val, :order, :now)
            RETURNING *
        """),
        {"pid": plan_id, "key": req.feature_key, "val": req.feature_value, "order": req.sort_order, "now": now},
    )
    await session.commit()
    await invalidate_all()
    r = result.fetchone()
    return FeatureResponse(id=r.id, feature_key=r.feature_key, feature_value=r.feature_value, sort_order=r.sort_order)


@router.delete("/plans/{plan_id}/features/{feature_id}")
async def delete_plan_feature(
    plan_id: int,
    feature_id: int,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _get_plan_or_404(session, plan_id)
    await session.execute(
        text("DELETE FROM plan_features WHERE id = :id AND plan_id = :pid"),
        {"id": feature_id, "pid": plan_id},
    )
    await session.commit()
    await invalidate_all()
    return {"status": "deleted", "id": feature_id}


@router.get("/usage", response_model=list[UsageStatsResponse])
async def list_usage_stats(
    tool: Optional[str] = None,
    plan_id: Optional[int] = None,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    query = """
        SELECT uu.user_id, uu.tool, uu.requests_used, uu.words_used,
               uu.period_start::text, uu.period_end::text
        FROM user_usage uu
    """
    conditions = []
    params = {}

    if tool:
        conditions.append("uu.tool = :tool")
        params["tool"] = tool
    if plan_id:
        query += " JOIN pricing_plans pp ON pp.legacy_plan_id IS NOT NULL"
        conditions.append("pp.id = :pid")
        params["pid"] = plan_id

    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY uu.period_start DESC, uu.requests_used DESC LIMIT 200"

    result = await session.execute(text(query), params)
    return [
        UsageStatsResponse(
            user_id=str(r.user_id),
            tool=r.tool,
            requests_used=r.requests_used,
            words_used=r.words_used,
            period_start=r.period_start,
            period_end=r.period_end,
        )
        for r in result.fetchall()
    ]


@router.get("/cache/stats")
async def cache_stats(
    current_user: User = Depends(get_admin_user),
):
    from app.cache import cache as cache_store
    return cache_store.stats()


@router.post("/cache/refresh")
async def force_refresh_cache(
    current_user: User = Depends(get_admin_user),
):
    from app.cache import cache as cache_store
    from app.cache.invalidation import invalidate_all
    await invalidate_all()
    await cache_store.load_all_plans()
    return {"status": "cache fully refreshed", "stats": cache_store.stats()}


@router.get("/usage/user/{user_id}", response_model=list[UsageStatsResponse])
async def get_user_usage_stats(
    user_id: str,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    result = await session.execute(
        text("""
            SELECT user_id, tool, requests_used, words_used,
                   period_start::text, period_end::text
            FROM user_usage
            WHERE user_id = :uid
            ORDER BY period_start DESC, tool ASC
        """),
        {"uid": user_id},
    )
    return [
        UsageStatsResponse(
            user_id=str(r.user_id),
            tool=r.tool,
            requests_used=r.requests_used,
            words_used=r.words_used,
            period_start=r.period_start,
            period_end=r.period_end,
        )
        for r in result.fetchall()
    ]


# ─────────────────────────────────────────────────────────
# COUPON SCHEMAS
# ─────────────────────────────────────────────────────────

class CouponCreate(BaseModel):
    code: str
    description: Optional[str] = None
    discount_type: str = "percentage"
    discount_value: float
    applies_to: str = "all"
    applies_to_billing: str = "both"
    max_uses: Optional[int] = None
    max_uses_per_user: int = 1
    min_plan_price: Optional[float] = None
    is_active: bool = True
    starts_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    plan_slugs: Optional[list[str]] = None

    @field_validator("discount_value")
    @classmethod
    def validate_discount(cls, v, info):
        if info.data.get("discount_type") == "percentage" and not (0 < v <= 100):
            raise ValueError("Percentage must be between 1 and 100")
        if info.data.get("discount_type") == "fixed" and v <= 0:
            raise ValueError("Fixed discount must be positive")
        return v

    @field_validator("code")
    @classmethod
    def upper_code(cls, v):
        return v.upper().strip()


class CouponUpdate(BaseModel):
    description: Optional[str] = None
    discount_type: Optional[str] = None
    discount_value: Optional[float] = None
    applies_to: Optional[str] = None
    applies_to_billing: Optional[str] = None
    max_uses: Optional[int] = None
    max_uses_per_user: Optional[int] = None
    min_plan_price: Optional[float] = None
    is_active: Optional[bool] = None
    starts_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    plan_slugs: Optional[list[str]] = None


class PlanDiscountUpdate(BaseModel):
    discount_percentage: Optional[float] = None
    show_original_price: Optional[bool] = None
    discount_label: Optional[str] = None


# ─────────────────────────────────────────────────────────
# COUPON CRUD
# ─────────────────────────────────────────────────────────

@router.get("/coupons")
async def list_coupons(
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    result = await session.execute(
        text("SELECT * FROM coupons ORDER BY created_at DESC")
    )
    rows = result.fetchall()
    now = datetime.now(timezone.utc)
    out = []
    for r in rows:
        plans = await session.execute(
            text("SELECT plan_slug FROM coupon_plan_limits WHERE coupon_id = :cid"),
            {"cid": r.id},
        )
        out.append({
            "id": r.id,
            "code": r.code,
            "description": r.description,
            "discount_type": r.discount_type,
            "discount_value": float(r.discount_value),
            "applies_to": r.applies_to,
            "applies_to_billing": r.applies_to_billing,
            "max_uses": r.max_uses,
            "uses_count": r.uses_count,
            "max_uses_per_user": r.max_uses_per_user,
            "min_plan_price": float(r.min_plan_price) if r.min_plan_price else None,
            "is_active": r.is_active,
            "starts_at": r.starts_at.isoformat() if r.starts_at else None,
            "expires_at": r.expires_at.isoformat() if r.expires_at else None,
            "is_expired": r.expires_at is not None and (r.expires_at.replace(tzinfo=timezone.utc) if r.expires_at.tzinfo is None else r.expires_at) < now,
            "is_maxed": r.max_uses is not None and r.uses_count >= r.max_uses,
            "plan_slugs": [p.plan_slug for p in plans.fetchall()],
            "created_at": r.created_at.isoformat(),
        })
    return out


@router.post("/coupons")
async def create_coupon(
    req: CouponCreate,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    existing = await session.execute(
        text("SELECT id FROM coupons WHERE code = :code"),
        {"code": req.code},
    )
    if existing.fetchone():
        raise BadRequestException(message=f"Coupon code '{req.code}' already exists")

    now = datetime.now(timezone.utc)
    row = await session.execute(
        text("""
            INSERT INTO coupons (code, description, discount_type, discount_value, applies_to,
               applies_to_billing, max_uses, max_uses_per_user, min_plan_price, is_active,
               starts_at, expires_at, created_at, updated_at)
            VALUES (:code, :desc, :dtype, :dval, :applies, :billing, :maxu, :peruser,
               :minprice, :active, :start, :expire, :now, :now)
            RETURNING id
        """),
        {
            "code": req.code, "desc": req.description, "dtype": req.discount_type,
            "dval": req.discount_value, "applies": req.applies_to,
            "billing": req.applies_to_billing, "maxu": req.max_uses,
            "peruser": req.max_uses_per_user, "minprice": req.min_plan_price,
            "active": req.is_active, "start": req.starts_at, "expire": req.expires_at,
            "now": now,
        },
    )
    coupon_id = row.fetchone().id

    if req.applies_to == "specific" and req.plan_slugs:
        for slug in req.plan_slugs:
            await session.execute(
                text("INSERT INTO coupon_plan_limits (coupon_id, plan_slug) VALUES (:cid, :slug) ON CONFLICT DO NOTHING"),
                {"cid": coupon_id, "slug": slug},
            )

    await session.commit()
    await invalidate_coupons()
    return {"status": "created", "code": req.code, "id": coupon_id}


@router.patch("/coupons/{code}")
async def update_coupon(
    code: str,
    req: CouponUpdate,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    code = code.upper()
    existing = await session.execute(
        text("SELECT id FROM coupons WHERE code = :code"),
        {"code": code},
    )
    row = existing.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Coupon not found")

    updates = []
    params = {"code": code}
    for field in ("description", "discount_type", "discount_value", "applies_to",
                  "applies_to_billing", "max_uses", "max_uses_per_user",
                  "min_plan_price", "is_active", "starts_at", "expires_at"):
        val = getattr(req, field, None)
        if val is not None:
            dbcol = field
            updates.append(f"{dbcol} = :{field}")
            params[field] = val

    if updates:
        updates.append("updated_at = :now")
        params["now"] = datetime.now(timezone.utc)
        await session.execute(
            text(f"UPDATE coupons SET {', '.join(updates)} WHERE code = :code"),
            params,
        )

    if req.plan_slugs is not None:
        await session.execute(
            text("DELETE FROM coupon_plan_limits WHERE coupon_id = :cid"),
            {"cid": row.id},
        )
        for slug in req.plan_slugs:
            await session.execute(
                text("INSERT INTO coupon_plan_limits (coupon_id, plan_slug) VALUES (:cid, :slug) ON CONFLICT DO NOTHING"),
                {"cid": row.id, "slug": slug},
            )

    await session.commit()
    await invalidate_coupons()
    return {"status": "updated", "code": code}


@router.delete("/coupons/{code}")
async def delete_coupon(
    code: str,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    code = code.upper()
    await session.execute(
        text("DELETE FROM coupons WHERE code = :code"),
        {"code": code},
    )
    await session.commit()
    await invalidate_coupons()
    return {"status": "deleted", "code": code}


@router.patch("/coupons/{code}/toggle")
async def toggle_coupon(
    code: str,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    code = code.upper()
    now = datetime.now(timezone.utc)
    await session.execute(
        text("UPDATE coupons SET is_active = NOT is_active, updated_at = :now WHERE code = :code"),
        {"code": code, "now": now},
    )
    await session.commit()
    await invalidate_coupons()
    return {"status": "toggled", "code": code}


@router.get("/coupons/{code}/usage")
async def get_coupon_usage(
    code: str,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    code = code.upper()
    result = await session.execute(
        text("""
            SELECT cu.*, c.code, c.discount_value, c.discount_type
            FROM coupon_usage cu
            JOIN coupons c ON c.id = cu.coupon_id
            WHERE c.code = :code
            ORDER BY cu.used_at DESC
        """),
        {"code": code},
    )
    return [dict(r) for r in result.fetchall()]


# ─────────────────────────────────────────────────────────
# PLAN PERMANENT DISCOUNT
# ─────────────────────────────────────────────────────────

@router.patch("/plans/{plan_slug}/discount")
async def set_plan_discount(
    plan_slug: str,
    req: PlanDiscountUpdate,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    now = datetime.now(timezone.utc)
    updates = []
    params = {"slug": plan_slug, "now": now}
    for field in ("discount_percentage", "show_original_price", "discount_label"):
        val = getattr(req, field, None)
        if val is not None:
            updates.append(f"{field} = :{field}")
            params[field] = val

    if not updates:
        raise BadRequestException(message="No fields to update")

    updates.append("updated_at = :now")
    await session.execute(
        text(f"UPDATE pricing_plans SET {', '.join(updates)} WHERE slug = :slug"),
        params,
    )
    await session.commit()

    from app.cache.invalidation import invalidate_plan
    await invalidate_plan(plan_slug)
    return {"status": "discount updated", "plan_slug": plan_slug}


@router.delete("/plans/{plan_slug}/discount")
async def remove_plan_discount(
    plan_slug: str,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    now = datetime.now(timezone.utc)
    await session.execute(
        text("""
            UPDATE pricing_plans SET
                discount_percentage = 0,
                show_original_price = false,
                discount_label = NULL,
                updated_at = :now
            WHERE slug = :slug
        """),
        {"slug": plan_slug, "now": now},
    )
    await session.commit()

    from app.cache.invalidation import invalidate_plan
    await invalidate_plan(plan_slug)
    return {"status": "discount removed", "plan_slug": plan_slug}
