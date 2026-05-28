from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class CheckoutRequest(BaseModel):
    plan_slug: str = Field(..., description="Plan slug (free, starter, creator, pro, unlimited)")
    billing_cycle: str = Field(default="monthly", pattern="^(monthly|yearly)$")


class CheckoutResponse(BaseModel):
    checkout_url: str
    plan_slug: str
    billing_cycle: str


class PlanChangeRequest(BaseModel):
    plan_slug: str = Field(..., description="Target plan slug")
    billing_cycle: str = Field(default="monthly", pattern="^(monthly|yearly)$")


class SubscriptionResponse(BaseModel):
    id: UUID
    user_id: UUID
    plan_id: UUID
    plan_name: str
    plan_slug: str
    status: str
    billing_interval: str
    paddle_subscription_id: Optional[str] = None
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class BillingDetail(BaseModel):
    plan_name: str
    plan_slug: str
    status: str
    billing_interval: str
    words_per_month: int
    words_per_request: int
    words_remaining: int
    current_period_end: Optional[datetime] = None
    paddle_customer_id: Optional[str] = None
    paddle_subscription_id: Optional[str] = None
    cancelled_at: Optional[datetime] = None
    scheduled_change: Optional[str] = None
