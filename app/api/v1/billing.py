import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends

logger = logging.getLogger(__name__)
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.core.exceptions import BadRequestException, NotFoundException, ForbiddenException
from app.core.config import settings
from app.db.models.user import User
from app.db.models.plan import Plan
from app.db.repositories.subscription_repo import SubscriptionRepository
from app.db.repositories.plan_repo import PlanRepository
from app.db.repositories.user_repo import UserRepository
from app.billing.paddle_client import (
    create_transaction,
    get_or_create_customer,
    create_customer_portal_session,
    create_product,
    create_price,
    get_subscription as paddle_get_subscription,
    cancel_subscription as paddle_cancel_subscription,
    list_customer_transactions,
)

router = APIRouter(prefix="/billing", tags=["billing"])


class CheckoutRequest(BaseModel):
    plan_slug: str
    billing_cycle: str = "monthly"


class CheckoutResponse(BaseModel):
    checkout_url: str
    transaction_id: str


class CancelResponse(BaseModel):
    status: str
    message: str


class PortalResponse(BaseModel):
    portal_url: str


class PlanSummary(BaseModel):
    id: str
    name: str
    slug: str
    words_per_month: int
    words_per_request: int
    modes: list[str]
    price_monthly: float
    price_yearly: float


class SubscriptionResponse(BaseModel):
    id: str
    plan: PlanSummary
    status: str
    billing_interval: str
    current_period_start: Optional[str] = None
    current_period_end: Optional[str] = None
    paddle_subscription_id: Optional[str] = None
    paddle_customer_id: Optional[str] = None
    scheduled_change: Optional[str] = None
    cancelled_at: Optional[str] = None
    created_at: str
    updated_at: str


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(
    req: CheckoutRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    plan_repo = PlanRepository(session)
    plan = await plan_repo.get_by_slug(req.plan_slug)

    if plan and not plan.is_active:
        raise BadRequestException(message="Plan is not available")

    if not plan:
        plan = await _resolve_plan_from_pricing(session, req.plan_slug, req.billing_cycle)
        if not plan:
            raise NotFoundException(message=f"Plan '{req.plan_slug}' not found")

    if req.billing_cycle == "yearly":
        price_id = plan.paddle_price_id_yearly
    else:
        price_id = plan.paddle_price_id_monthly

    if not price_id:
        price_id = await _ensure_paddle_price(session, plan, req.billing_cycle)

    try:
        customer_id = await get_or_create_customer(
            current_user.email,
            name=current_user.full_name,
        )

        sub_repo = SubscriptionRepository(session)
        existing_sub = await sub_repo.get_by_user(current_user.id)
        if existing_sub and existing_sub.paddle_customer_id:
            customer_id = existing_sub.paddle_customer_id

        if existing_sub and existing_sub.paddle_subscription_id:
            existing_sub.paddle_customer_id = customer_id
            await sub_repo.update(existing_sub.id, {"paddle_customer_id": customer_id})

        transaction = await create_transaction(
            price_id=price_id,
            customer_id=customer_id,
        )

        checkout_url = None
        if "checkout" in transaction:
            checkout_data = transaction["checkout"]
            if isinstance(checkout_data, dict):
                checkout_url = checkout_data.get("url")
        if not checkout_url:
            checkout_url = transaction.get("urls", {}).get("checkout")

        if not checkout_url:
            checkout_url = transaction.get("url")

        if not checkout_url:
            checkout_url = f"https://checkout.paddle.com/checkout/custom/{transaction.get('id', '')}"

        txn_id = transaction.get("id", "")
        return CheckoutResponse(checkout_url=checkout_url, transaction_id=txn_id)

    except Exception as e:
        logger.error("Checkout failed for plan=%s cycle=%s user=%s: %s",
                      req.plan_slug, req.billing_cycle, current_user.email, str(e))
        raise BadRequestException(
            message=f"Checkout failed: {str(e)}",
            detail={"plan_slug": req.plan_slug, "billing_cycle": req.billing_cycle},
        )


async def _resolve_plan_from_pricing(
    session: AsyncSession,
    plan_slug: str,
    billing_cycle: str,
) -> Plan | None:
    result = await session.execute(
        text("SELECT * FROM pricing_plans WHERE slug = :slug"),
        {"slug": plan_slug},
    )
    row = result.fetchone()
    if not row:
        return None

    if row.legacy_plan_id:
        plan_repo = PlanRepository(session)
        existing = await plan_repo.get_by_id(row.legacy_plan_id)
        if existing:
            return existing

    now = datetime.now(timezone.utc)
    plan = Plan(
        id=uuid.uuid4(),
        name=row.name,
        slug=row.slug,
        description=row.description or f"{row.name} plan",
        price_monthly=float(row.monthly_price_usd) if row.monthly_price_usd else 0,
        price_yearly=float(row.annual_price_usd) if row.annual_price_usd else 0,
        paddle_price_id_monthly=row.paddle_monthly_price_id,
        paddle_price_id_yearly=row.paddle_annual_price_id,
        words_per_month=getattr(row, 'max_words_per_month', -1) if getattr(row, 'max_words_per_month', -1) is not None else -1,
        words_per_request=3000,
        modes=["standard"],
        is_active=row.is_active if hasattr(row, 'is_active') else True,
        sort_order=row.display_order if hasattr(row, 'display_order') else 99,
        is_featured=row.is_featured if hasattr(row, 'is_featured') else False,
    )
    session.add(plan)
    await session.flush()

    await session.execute(
        text("UPDATE pricing_plans SET legacy_plan_id = :pid WHERE slug = :slug"),
        {"pid": plan.id, "slug": plan_slug},
    )
    await session.commit()
    return plan


async def _ensure_paddle_price(
    session: AsyncSession,
    plan: Plan,
    billing_cycle: str,
) -> str:
    product_id = plan.paddle_product_id
    if not product_id:
        product_id = await create_product(
            name=plan.name,
            description=plan.description or f"{plan.name} plan",
        )
        if not product_id:
            raise BadRequestException(message="Failed to create Paddle product")

    if billing_cycle == "yearly":
        amount_annual_cents = str(int(plan.price_yearly * 100))
        price_id = await create_price(
            product_id=product_id,
            name=f"{plan.name} Yearly",
            description=f"{plan.name} - annual subscription",
            amount=amount_annual_cents,
            interval="year",
        )
        plan.paddle_price_id_yearly = price_id
    else:
        amount_monthly_cents = str(int(plan.price_monthly * 100))
        price_id = await create_price(
            product_id=product_id,
            name=f"{plan.name} Monthly",
            description=f"{plan.name} - monthly subscription",
            amount=amount_monthly_cents,
            interval="month",
        )
        plan.paddle_price_id_monthly = price_id

    plan.paddle_product_id = product_id
    await session.flush()

    await session.execute(
        text("UPDATE pricing_plans SET paddle_monthly_price_id = :m, paddle_annual_price_id = :a WHERE slug = :slug"),
        {
            "m": plan.paddle_price_id_monthly,
            "a": plan.paddle_price_id_yearly,
            "slug": plan.slug,
        },
    )
    await session.commit()

    if not price_id:
        raise BadRequestException(message=f"Failed to create Paddle price for {billing_cycle} billing")

    return price_id


@router.post("/cancel", response_model=CancelResponse)
async def cancel_subscription(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    sub_repo = SubscriptionRepository(session)
    subscription = await sub_repo.get_by_user(current_user.id)
    if not subscription:
        raise NotFoundException(message="No active subscription found")

    if subscription.status not in ("active", "trialing"):
        raise BadRequestException(
            message=f"Subscription is already {subscription.status}",
            detail={"status": subscription.status},
        )

    if subscription.paddle_subscription_id:
        try:
            success = await paddle_cancel_subscription(subscription.paddle_subscription_id)
            if not success:
                raise RuntimeError("Paddle API returned failure")
        except Exception as e:
            raise BadRequestException(
                message="Failed to cancel subscription in Paddle",
                detail={"error": str(e)},
            )

    updated = await sub_repo.cancel(subscription.id)
    if not updated:
        raise NotFoundException(message="Failed to cancel subscription")

    return CancelResponse(
        status="canceled",
        message="Subscription will be canceled at the end of the current billing period",
    )


@router.get("/portal", response_model=PortalResponse)
async def get_portal(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    sub_repo = SubscriptionRepository(session)
    subscription = await sub_repo.get_by_user(current_user.id)

    customer_id = None
    if subscription and subscription.paddle_customer_id:
        customer_id = subscription.paddle_customer_id
    else:
        try:
            customer_id = await get_or_create_customer(
                current_user.email,
                name=current_user.full_name,
            )
        except Exception as e:
            raise BadRequestException(
                message="Failed to get or create customer",
                detail={"error": str(e)},
            )

    try:
        portal_url = await create_customer_portal_session(customer_id)
        if not portal_url:
            raise RuntimeError("Paddle returned no portal URL")
    except Exception as e:
        raise BadRequestException(
            message="Failed to create portal session",
            detail={"error": str(e)},
        )

    return PortalResponse(portal_url=portal_url)


@router.get("/subscription", response_model=SubscriptionResponse)
async def get_subscription(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    sub_repo = SubscriptionRepository(session)
    subscription = await sub_repo.get_by_user(current_user.id)

    if not subscription:
        raise NotFoundException(message="No active subscription found")

    plan_repo = PlanRepository(session)
    plan = await plan_repo.get_by_id(subscription.plan_id)

    return SubscriptionResponse(
        id=str(subscription.id),
        plan=PlanSummary(
            id=str(plan.id) if plan else "",
            name=plan.name if plan else "Free",
            slug=plan.slug if plan else "free",
            words_per_month=plan.words_per_month if plan else 500,
            words_per_request=plan.words_per_request if plan else 200,
            modes=plan.modes or [] if plan else ["standard"],
            price_monthly=plan.price_monthly if plan else 0,
            price_yearly=plan.price_yearly if plan else 0,
        ),
        status=subscription.status,
        billing_interval=subscription.billing_interval,
        current_period_start=subscription.current_period_start.isoformat() if subscription.current_period_start else None,
        current_period_end=subscription.current_period_end.isoformat() if subscription.current_period_end else None,
        paddle_subscription_id=subscription.paddle_subscription_id,
        paddle_customer_id=subscription.paddle_customer_id,
        scheduled_change=subscription.scheduled_change,
        cancelled_at=subscription.cancelled_at.isoformat() if subscription.cancelled_at else None,
        created_at=subscription.created_at.isoformat(),
        updated_at=subscription.updated_at.isoformat(),
    )


class TransactionItem(BaseModel):
    id: str
    plan_name: Optional[str] = None
    billing_cycle: Optional[str] = None
    status: str
    amount: float
    currency: str
    payment_method: Optional[str] = None
    invoice_url: Optional[str] = None
    receipt_url: Optional[str] = None
    paid_at: Optional[str] = None
    created_at: str


class TransactionListResponse(BaseModel):
    items: list[TransactionItem]
    total: int


@router.get("/transactions", response_model=TransactionListResponse)
async def get_transactions(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    from app.db.repositories.transaction_repo import TransactionRepository
    repo = TransactionRepository(session)
    txns, total = await repo.get_by_user(current_user.id, limit=100)

    items = []
    for txn in txns:
        items.append(
            TransactionItem(
                id=str(txn.id),
                plan_name=txn.plan_name,
                billing_cycle=txn.billing_cycle,
                status=txn.status,
                amount=float(txn.amount),
                currency=txn.currency,
                payment_method=txn.payment_method,
                invoice_url=txn.invoice_url,
                receipt_url=txn.receipt_url,
                paid_at=txn.paid_at.isoformat() if txn.paid_at else None,
                created_at=txn.created_at.isoformat(),
            )
        )

    if not txns:
        sub_repo = SubscriptionRepository(session)
        sub = await sub_repo.get_by_user(current_user.id)
        if sub and sub.paddle_customer_id:
            try:
                paddle_txns = await list_customer_transactions(sub.paddle_customer_id)
                for pt in paddle_txns:
                    txn_id = pt.get("id", "")
                    existing = await repo.get_by_paddle_id(txn_id)
                    if existing:
                        continue
                    details = pt.get("details", {})
                    line_items = details.get("line_items", [])
                    plan_name = None
                    billing_cycle = None
                    amount = 0
                    for item in line_items:
                        price = item.get("price", {})
                        product = price.get("product", {})
                        if product:
                            plan_name = product.get("name") or plan_name
                        billing = price.get("billing_cycle", {})
                        if billing:
                            interval = billing.get("interval", "")
                            billing_cycle = "yearly" if interval == "year" else "monthly"
                        unit_price = price.get("unit_price", {})
                        item_amount = unit_price.get("amount", "0")
                        qty = item.get("quantity", 1)
                        try:
                            amount += float(item_amount) * qty
                        except (ValueError, TypeError):
                            pass
                    payouts = pt.get("payouts", [])
                    payment_method = None
                    if payouts:
                        payment_method = payouts[0].get("type")
                    invoices = pt.get("invoices", [])
                    invoice_url = invoices[0].get("url") if invoices else None
                    receipt_url = invoices[0].get("receipt_url") if invoices else None
                    paid_at_str = pt.get("paid_at") or pt.get("created_at")
                    paid_at = None
                    if paid_at_str:
                        try:
                            paid_at = datetime.fromisoformat(paid_at_str.replace("Z", "+00:00"))
                        except (ValueError, AttributeError):
                            pass
                    pt_status = pt.get("status", "completed")

                    from decimal import Decimal
                    txn = await repo.upsert_from_paddle(
                        user_id=current_user.id,
                        paddle_id=txn_id,
                        customer_id=sub.paddle_customer_id,
                        plan_name=plan_name,
                        billing_cycle=billing_cycle,
                        status=pt_status,
                        amount=Decimal(str(amount)).quantize(Decimal("0.01")),
                        currency="USD",
                        payment_method=payment_method,
                        invoice_url=invoice_url,
                        receipt_url=receipt_url,
                        paid_at=paid_at,
                    )
                    items.append(
                        TransactionItem(
                            id=str(txn.id),
                            plan_name=txn.plan_name,
                            billing_cycle=txn.billing_cycle,
                            status=txn.status,
                            amount=float(txn.amount),
                            currency=txn.currency,
                            payment_method=txn.payment_method,
                            invoice_url=txn.invoice_url,
                            receipt_url=txn.receipt_url,
                            paid_at=txn.paid_at.isoformat() if txn.paid_at else None,
                            created_at=txn.created_at.isoformat(),
                        )
                    )
            except Exception as e:
                logger.error("Failed to fetch transactions from Paddle: %s", e)

    return TransactionListResponse(items=items, total=len(items))
