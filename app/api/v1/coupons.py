from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session

router = APIRouter(prefix="/coupons", tags=["coupons"])


class CouponValidateRequest(BaseModel):
    code: str
    plan_slug: str
    billing: str
    user_id: str


@router.post("/validate")
async def validate_coupon(
    req: CouponValidateRequest,
    session: AsyncSession = Depends(get_db_session),
):
    code = req.code.upper()
    now = datetime.now(timezone.utc)

    coupon = await session.execute(
        text("SELECT * FROM coupons WHERE code = :code AND is_active = true"),
        {"code": code},
    )
    c = coupon.fetchone()
    if not c:
        return {"valid": False, "reason": "Coupon not found or inactive"}

    if c.expires_at and c.expires_at.replace(tzinfo=timezone.utc) < now:
        return {"valid": False, "reason": "Coupon has expired"}

    if c.starts_at and c.starts_at.replace(tzinfo=timezone.utc) > now:
        return {"valid": False, "reason": "Coupon not yet active"}

    if c.max_uses and c.uses_count >= c.max_uses:
        return {"valid": False, "reason": "Coupon usage limit reached"}

    user_uses = await session.execute(
        text("SELECT COUNT(*) FROM coupon_usage WHERE coupon_id = :cid AND user_id = :uid"),
        {"cid": c.id, "uid": req.user_id},
    )
    if user_uses.scalar_one() >= c.max_uses_per_user:
        return {"valid": False, "reason": "You have already used this coupon"}

    if c.applies_to_billing != "both" and c.applies_to_billing != req.billing:
        return {"valid": False, "reason": f"Coupon only applies to {c.applies_to_billing} billing"}

    if c.applies_to == "specific":
        allowed = await session.execute(
            text("SELECT COUNT(*) FROM coupon_plan_limits WHERE coupon_id = :cid AND plan_slug = :slug"),
            {"cid": c.id, "slug": req.plan_slug},
        )
        if not allowed.scalar_one():
            return {"valid": False, "reason": "Coupon not valid for this plan"}

    plan = await session.execute(
        text("SELECT monthly_price_usd, annual_price_usd FROM pricing_plans WHERE slug = :slug"),
        {"slug": req.plan_slug},
    )
    p = plan.fetchone()
    if not p:
        return {"valid": False, "reason": "Plan not found"}

    original_price = float(p.monthly_price_usd if req.billing == "monthly" else p.annual_price_usd)

    if c.min_plan_price and original_price < float(c.min_plan_price):
        return {"valid": False, "reason": f"Coupon requires minimum plan price of ${float(c.min_plan_price):.2f}"}

    if c.discount_type == "percentage":
        discount_amount = round(original_price * float(c.discount_value) / 100, 2)
    else:
        discount_amount = min(float(c.discount_value), original_price)

    final_price = round(original_price - discount_amount, 2)

    return {
        "valid": True,
        "code": c.code,
        "discount_type": c.discount_type,
        "discount_value": float(c.discount_value),
        "original_price": original_price,
        "discount_amount": discount_amount,
        "final_price": final_price,
        "billing": req.billing,
        "description": c.description,
    }


@router.post("/apply")
async def apply_coupon(
    req: CouponValidateRequest,
    session: AsyncSession = Depends(get_db_session),
):
    code = req.code.upper()
    c = await session.execute(
        text("SELECT * FROM coupons WHERE code = :code"),
        {"code": code},
    )
    c = c.fetchone()
    if not c:
        return {"status": "error", "reason": "Coupon not found"}

    plan = await session.execute(
        text("SELECT monthly_price_usd, annual_price_usd FROM pricing_plans WHERE slug = :slug"),
        {"slug": req.plan_slug},
    )
    p = plan.fetchone()
    original = float(p.monthly_price_usd if req.billing == "monthly" else p.annual_price_usd)

    if c.discount_type == "percentage":
        discount = round(original * float(c.discount_value) / 100, 2)
    else:
        discount = min(float(c.discount_value), original)

    await session.execute(
        text("""
            INSERT INTO coupon_usage (coupon_id, user_id, plan_slug, billing, discount_applied)
            VALUES (:cid, :uid, :slug, :billing, :discount)
        """),
        {"cid": c.id, "uid": req.user_id, "slug": req.plan_slug, "billing": req.billing, "discount": discount},
    )

    await session.execute(
        text("UPDATE coupons SET uses_count = uses_count + 1 WHERE id = :id"),
        {"id": c.id},
    )

    await session.commit()
    return {"status": "applied", "discount_applied": discount}
