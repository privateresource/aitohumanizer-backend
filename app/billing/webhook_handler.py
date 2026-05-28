import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.paddle_event import PaddleEvent
from app.db.models.subscription import Subscription
from app.db.models.user import User
from app.db.repositories.subscription_repo import SubscriptionRepository
from app.db.repositories.plan_repo import PlanRepository
from app.db.repositories.user_repo import UserRepository

logger = logging.getLogger(__name__)

PADDLE_SIGNATURE_TTL = 300  # 5 minutes


async def verify_paddle_signature(request: Request, raw_body: bytes) -> bool:
    signature_header = request.headers.get("Paddle-Signature", "")
    if not signature_header:
        logger.warning("Missing Paddle-Signature header")
        return False

    parts = {}
    for item in signature_header.split(";"):
        if "=" in item:
            key, value = item.split("=", 1)
            parts[key.strip()] = value.strip()

    ts_str = parts.get("ts")
    h1 = parts.get("h1")
    if not ts_str or not h1:
        logger.warning("Invalid Paddle-Signature format")
        return False

    try:
        ts = int(ts_str)
    except ValueError:
        logger.warning("Invalid Paddle timestamp")
        return False

    now = int(time.time())
    if abs(now - ts) > PADDLE_SIGNATURE_TTL:
        logger.warning("Paddle webhook timestamp too old (replay attack?)")
        return False

    expected = hmac.new(
        settings.paddle_webhook_secret.encode("utf-8"),
        f"{ts_str}:{raw_body.decode('utf-8')}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, h1):
        logger.warning("Paddle webhook signature mismatch")
        return False

    return True


async def process_webhook(
    request: Request,
    raw_body: bytes,
    session: AsyncSession,
) -> dict:
    verified = await verify_paddle_signature(request, raw_body)
    if not verified:
        return {"status": "ignored", "reason": "invalid_signature"}

    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        return {"status": "ignored", "reason": "invalid_json"}

    event_id = body.get("event_id", "")
    event_type = body.get("event_type", "")
    data = body.get("data", {})

    paddle_event_repo = PaddleEventRepository(session)
    existing = await paddle_event_repo.get_by_event_id(event_id)
    if existing:
        return {"status": "duplicate", "event_type": event_type}

    paddle_event = PaddleEvent(
        paddle_event_id=event_id,
        event_type=event_type,
        processed=False,
        raw_body=raw_body.decode("utf-8"),
    )
    await paddle_event_repo.create(paddle_event)

    handler_map = {
        "subscription.created": _handle_subscription_created,
        "subscription.updated": _handle_subscription_updated,
        "subscription.canceled": _handle_subscription_canceled,
        "subscription.activated": _handle_subscription_activated,
        "transaction.completed": _handle_transaction_completed,
        "customer.updated": _handle_customer_updated,
    }

    handler = handler_map.get(event_type)
    if handler:
        try:
            await handler(data, session)
        except Exception as e:
            logger.error("Webhook handler error for %s: %s", event_type, e)
            await paddle_event_repo.mark_processed(paddle_event.id, success=False)
            return {"status": "error", "event_type": event_type, "error": str(e)}

    await paddle_event_repo.mark_processed(paddle_event.id)
    return {"status": "processed", "event_type": event_type}


async def _handle_subscription_created(data: dict, session: AsyncSession):
    repo = SubscriptionRepository(session)
    paddle_id = data.get("id")
    customer_id = data.get("customer_id")
    customer_email = data.get("customer_email") or data.get("email")
    status = data.get("status", "active")
    items = data.get("items", [])
    price_id = items[0].get("price", {}).get("id") if items else None

    user_repo = UserRepository(session)
    plan_repo = PlanRepository(session)

    if hasattr(user_repo, 'get_by_paddle_customer_id'):
        user = await user_repo.get_by_paddle_customer_id(customer_id)
    else:
        user = None
    if not user and customer_email:
        user = await user_repo.get_by_email(customer_email)

    plan = await plan_repo.get_by_paddle_price_id(price_id) if hasattr(plan_repo, 'get_by_paddle_price_id') else None

    existing = await repo.get_by_paddle_id(paddle_id)
    if existing:
        return

    sub = Subscription(
        user_id=getattr(user, "id", None),
        plan_id=getattr(plan, "id", None),
        paddle_subscription_id=paddle_id,
        paddle_customer_id=customer_id,
        status=status,
        current_period_start=_parse_dt(data.get("started_at")),
        current_period_end=_parse_dt(data.get("current_period_end")),
        billing_interval=_extract_interval(items),
    )
    await repo.create(sub)


async def _handle_subscription_updated(data: dict, session: AsyncSession):
    repo = SubscriptionRepository(session)
    paddle_id = data.get("id")
    sub = await repo.get_by_paddle_id(paddle_id)
    if not sub:
        return

    status = data.get("status", sub.status)
    items = data.get("items", [])
    billing_interval = _extract_interval(items) or sub.billing_interval
    scheduled_change = data.get("scheduled_change")

    update_data = {
        "status": status,
        "current_period_start": _parse_dt(data.get("started_at")) or sub.current_period_start,
        "current_period_end": _parse_dt(data.get("current_period_end")) or sub.current_period_end,
        "billing_interval": billing_interval,
        "scheduled_change": json.dumps(scheduled_change) if scheduled_change else None,
    }
    await repo.update(sub.id, update_data)


async def _handle_subscription_canceled(data: dict, session: AsyncSession):
    repo = SubscriptionRepository(session)
    paddle_id = data.get("id")
    sub = await repo.get_by_paddle_id(paddle_id)
    if not sub:
        return
    await repo.cancel(sub.id)


async def _handle_subscription_activated(data: dict, session: AsyncSession):
    repo = SubscriptionRepository(session)
    paddle_id = data.get("id")
    sub = await repo.get_by_paddle_id(paddle_id)
    if not sub:
        return
    await repo.update(sub.id, {"status": "active", "cancelled_at": None})


async def _handle_transaction_completed(data: dict, session: AsyncSession):
    logger.info("Transaction completed: %s", data.get("id"))


async def _handle_customer_updated(data: dict, session: AsyncSession):
    logger.info("Customer updated: %s", data.get("id"))


def _parse_dt(dt_str: Optional[str]):
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _extract_interval(items: list) -> str:
    if not items:
        return "monthly"
    price = items[0].get("price", {})
    billing = price.get("billing_cycle", {})
    interval = billing.get("interval", "month")
    return "yearly" if interval == "year" else "monthly"


class PaddleEventRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_event_id(self, event_id: str):
        from sqlalchemy import select
        result = await self.session.execute(
            select(PaddleEvent).where(PaddleEvent.paddle_event_id == event_id)
        )
        return result.scalar_one_or_none()

    async def create(self, event: PaddleEvent) -> PaddleEvent:
        self.session.add(event)
        await self.session.commit()
        await self.session.refresh(event)
        return event

    async def mark_processed(self, event_id, success=True):
        from sqlalchemy import update
        stmt = (
            update(PaddleEvent)
            .where(PaddleEvent.id == event_id)
            .values(processed=success, processed_at=datetime.now(timezone.utc))
        )
        await self.session.execute(stmt)
        await self.session.commit()
