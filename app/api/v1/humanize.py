import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.core.constants import PLAN_LIMITS, ANON_LIMITS, WORD_COSTS
from app.core.exceptions import BadRequestException, QuotaExceededException, ForbiddenException, ServiceUnavailableException
from app.db.models.user import User
from app.db.models.humanize_request import HumanizeRequest
from app.db.models.word_usage import WordUsage
from app.db.repositories.humanize_repo import HumanizeRepository
from app.db.repositories.word_usage_repo import WordUsageRepository
from app.db.repositories.subscription_repo import SubscriptionRepository
from app.db.repositories.plan_repo import PlanRepository
from app.llm.router import humanize_text as llm_humanize, paraphrase_text as llm_paraphrase

router = APIRouter(prefix="/humanize", tags=["humanize"])

_anon_sessions: dict[str, int] = {}


class HumanizeRequestPayload(BaseModel):
    text: str
    mode: str = "standard"
    preferred_provider_id: Optional[str] = None
    session_id: Optional[str] = None
    mood: Optional[str] = None


class HumanizeResponse(BaseModel):
    humanized: str
    words_humanized: int
    words_remaining: Optional[int] = None
    words_total_this_month: Optional[int] = None
    quota_pct_remaining: Optional[float] = None
    quota_urgency: str = "good"
    mode_used: str
    provider_used: str
    duration_ms: int


class PreviewResponse(BaseModel):
    humanized: str
    words_used: int
    session_id: str
    requests_remaining: int
    cta: str


class PreviewLimitResponse(BaseModel):
    error: str = "preview_limit_reached"
    cta: str = "signup"


@router.post("/preview", response_model=PreviewResponse, status_code=200)
async def preview_humanize(
    req: HumanizeRequestPayload,
    session: AsyncSession = Depends(get_db_session),
):
    word_count = len(req.text.split())

    if word_count > ANON_LIMITS["max_words"]:
        raise BadRequestException(
            message=f"Preview limited to {ANON_LIMITS['max_words']} words",
            detail={"max_words": ANON_LIMITS["max_words"], "sent": word_count},
        )

    session_id = req.session_id or str(uuid.uuid4())

    existing_count = _anon_sessions.get(session_id, 0)
    if existing_count == 0:
        anon_repo = HumanizeRepository(session)
        existing_requests, total = await anon_repo.get_by_session(session_id, limit=1)
        if existing_requests:
            _anon_sessions[session_id] = len(existing_requests)

    used = _anon_sessions.get(session_id, 0)
    requests_remaining = ANON_LIMITS["max_requests_per_session"] - used
    if used >= ANON_LIMITS["max_requests_per_session"]:
        raise HTTPException(status_code=402, detail=PreviewLimitResponse().model_dump())

    llm_result = await llm_humanize(
        text=req.text,
        mode=req.mode,
        preferred_provider_id=req.preferred_provider_id,
    )

    if llm_result.get("error") and not llm_result.get("humanized_text"):
        raise ServiceUnavailableException(
            message="Humanization service is unavailable right now. Please try again later.",
            detail={"error": llm_result["error"]},
        )

    humanized_text = llm_result.get("humanized_text") or req.text
    duration_ms = llm_result.get("duration_ms", 0)

    humanize_req = HumanizeRequest(
        user_id=None,
        anonymous_session_id=session_id,
        input_text=req.text,
        output_text=humanized_text,
        mode=req.mode,
        word_count=word_count,
        processing_time_ms=duration_ms,
        status="completed",
        is_anonymous=True,
        ai_model=llm_result.get("model"),
    )
    await HumanizeRepository(session).create(humanize_req)

    _anon_sessions[session_id] = used + 1
    remaining = ANON_LIMITS["max_requests_per_session"] - _anon_sessions[session_id]

    return PreviewResponse(
        humanized=humanized_text,
        words_used=word_count,
        session_id=session_id,
        requests_remaining=max(0, remaining),
        cta="signup",
    )


@router.post("", response_model=HumanizeResponse)
async def humanize_text(
    req: HumanizeRequestPayload,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    word_count = len(req.text.split())

    if word_count == 0:
        raise BadRequestException(message="Text is empty")

    sub_repo = SubscriptionRepository(session)
    plan_repo = PlanRepository(session)
    word_repo = WordUsageRepository(session)

    subscription = await sub_repo.get_by_user(current_user.id)
    if not subscription:
        plan_slug = "free"
        plan_limits = PLAN_LIMITS.get("free", {})
    else:
        plan = await plan_repo.get_by_id(subscription.plan_id)
        if not plan:
            raise BadRequestException(message="Plan not found for subscription")
        plan_slug = plan.slug
        plan_limits = {
            "words_per_month": plan.words_per_month,
            "words_per_request": plan.words_per_request,
            "modes": plan.modes or [],
        }
        pp_result = await session.execute(
            text("SELECT max_words_per_month FROM pricing_plans WHERE slug = :slug"),
            {"slug": plan.slug},
        )
        pp_row = pp_result.fetchone()
        if pp_row and pp_row.max_words_per_month is not None:
            plan_limits["words_per_month"] = pp_row.max_words_per_month

    if subscription and subscription.status not in ("active", "trialing"):
        raise ForbiddenException(
            message="Subscription is not active",
            detail={"status": subscription.status},
        )

    max_per_request = plan_limits.get("words_per_request", 200)
    if word_count > max_per_request:
        raise BadRequestException(
            message=f"Word count exceeds plan limit of {max_per_request}",
            detail={"max_per_request": max_per_request, "sent": word_count},
        )

    words_per_month = plan_limits.get("words_per_month", 500)
    if words_per_month != -1:
        words_remaining = await word_repo.get_balance(current_user.id, words_per_month)
        word_cost = WORD_COSTS.get(req.mode, 1)
        words_needed = word_count * word_cost

        if words_remaining < words_needed:
            pct = (words_remaining / words_per_month * 100) if words_per_month > 0 else 0
            raise QuotaExceededException(
                message="Word quota exceeded",
                detail={
                    "words_remaining": words_remaining,
                    "words_needed": words_needed,
                    "words_per_month": words_per_month,
                    "quota_pct_remaining": round(pct, 1),
                },
            )
    else:
        words_remaining = 999999999

    llm_result = await llm_humanize(
        text=req.text,
        mode=req.mode,
        preferred_provider_id=req.preferred_provider_id,
        db=session,
        user_id=str(current_user.id),
        mood=req.mood,
    )

    if llm_result.get("error") and not llm_result.get("humanized_text"):
        raise ServiceUnavailableException(
            message="Humanization service is unavailable right now. Please try again later.",
            detail={"error": llm_result["error"]},
        )

    humanized_text = llm_result.get("humanized_text") or req.text
    duration_ms = llm_result.get("duration_ms", 0)

    humanize_req = HumanizeRequest(
        user_id=current_user.id,
        anonymous_session_id=req.session_id,
        input_text=req.text,
        output_text=humanized_text,
        mode=req.mode,
        word_count=word_count,
        tokens_used=llm_result.get("tokens_used", 0),
        processing_time_ms=duration_ms,
        status="completed",
        is_anonymous=False,
        ai_model=llm_result.get("model"),
    )
    humanize_repo = HumanizeRepository(session)
    created = await humanize_repo.create(humanize_req)

    if words_per_month != -1:
        word_cost = WORD_COSTS.get(req.mode, 1)
        deduction = word_count * word_cost
        period = datetime.now(timezone.utc).strftime("%Y-%m")
        new_remaining = words_remaining - deduction

        usage_entry = WordUsage(
            user_id=current_user.id,
            words_delta=-deduction,
            words_balance_after=new_remaining,
            event_type="humanize_use",
            reference_id=created.id,
            billing_period=period,
            description=f"Humanize request ({req.mode})",
        )
        await word_repo.add_entry(usage_entry)
    else:
        new_remaining = 999999999

    words_per_month_val = words_per_month
    if words_per_month_val == -1:
        quota_pct = 100.0
        total_this_month = 0
    else:
        total_this_month = words_per_month_val - new_remaining
        quota_pct = (new_remaining / words_per_month_val * 100) if words_per_month_val > 0 else 0

    if quota_pct > 50:
        urgency = "good"
    elif quota_pct > 20:
        urgency = "low"
    elif quota_pct > 10:
        urgency = "medium"
    else:
        urgency = "critical"

    return HumanizeResponse(
        humanized=humanized_text,
        words_humanized=word_count,
        words_remaining=new_remaining,
        words_total_this_month=total_this_month if words_per_month_val != -1 else None,
        quota_pct_remaining=round(quota_pct, 1),
        quota_urgency=urgency,
        mode_used=req.mode,
        provider_used=llm_result.get("provider", "unknown"),
        duration_ms=duration_ms,
    )


class ParaphraseRequestPayload(BaseModel):
    text: str
    mode: str = "standard"
    mood: Optional[str] = None


@router.post("/paraphrase", response_model=HumanizeResponse)
async def paraphrase_text_endpoint(
    req: ParaphraseRequestPayload,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    word_count = len(req.text.split())

    if word_count == 0:
        raise BadRequestException(message="Text is empty")

    sub_repo = SubscriptionRepository(session)
    plan_repo = PlanRepository(session)
    word_repo = WordUsageRepository(session)

    subscription = await sub_repo.get_by_user(current_user.id)
    if not subscription:
        plan_slug = "free"
        plan_limits = PLAN_LIMITS.get("free", {})
    else:
        plan = await plan_repo.get_by_id(subscription.plan_id)
        if not plan:
            raise BadRequestException(message="Plan not found for subscription")
        plan_slug = plan.slug
        plan_limits = {
            "words_per_month": plan.words_per_month,
            "words_per_request": plan.words_per_request,
            "modes": plan.modes or [],
        }
        pp_result = await session.execute(
            text("SELECT max_words_per_month FROM pricing_plans WHERE slug = :slug"),
            {"slug": plan.slug},
        )
        pp_row = pp_result.fetchone()
        if pp_row and pp_row.max_words_per_month is not None:
            plan_limits["words_per_month"] = pp_row.max_words_per_month

    if subscription and subscription.status not in ("active", "trialing"):
        raise ForbiddenException(
            message="Subscription is not active",
            detail={"status": subscription.status},
        )

    max_per_request = plan_limits.get("words_per_request", 200)
    if word_count > max_per_request:
        raise BadRequestException(
            message=f"Word count exceeds plan limit of {max_per_request}",
            detail={"max_per_request": max_per_request, "sent": word_count},
        )

    words_per_month = plan_limits.get("words_per_month", 500)
    if words_per_month != -1:
        words_remaining = await word_repo.get_balance(current_user.id, words_per_month)
        word_cost = WORD_COSTS.get(req.mode, 1)
        words_needed = word_count * word_cost

        if words_remaining < words_needed:
            pct = (words_remaining / words_per_month * 100) if words_per_month > 0 else 0
            raise QuotaExceededException(
                message="Word quota exceeded",
                detail={
                    "words_remaining": words_remaining,
                    "words_needed": words_needed,
                    "words_per_month": words_per_month,
                    "quota_pct_remaining": round(pct, 1),
                },
            )
    else:
        words_remaining = 999999999

    llm_result = await llm_paraphrase(
        text=req.text,
        mode=req.mode,
        db=session,
        user_id=str(current_user.id),
        mood=req.mood,
    )

    if llm_result.get("error") and not llm_result.get("humanized_text"):
        raise ServiceUnavailableException(
            message="Paraphrasing service is unavailable right now. Please try again later.",
            detail={"error": llm_result["error"]},
        )

    paraphrased_text = llm_result.get("humanized_text") or req.text
    duration_ms = llm_result.get("duration_ms", 0)

    humanize_req = HumanizeRequest(
        user_id=current_user.id,
        input_text=req.text,
        output_text=paraphrased_text,
        mode=f"paraphrase_{req.mode}",
        word_count=word_count,
        tokens_used=llm_result.get("tokens_used", 0),
        processing_time_ms=duration_ms,
        status="completed",
        is_anonymous=False,
        ai_model=llm_result.get("model"),
    )
    humanize_repo = HumanizeRepository(session)
    created = await humanize_repo.create(humanize_req)

    if words_per_month != -1:
        word_cost = WORD_COSTS.get(req.mode, 1)
        deduction = word_count * word_cost
        period = datetime.now(timezone.utc).strftime("%Y-%m")
        new_remaining = words_remaining - deduction

        usage_entry = WordUsage(
            user_id=current_user.id,
            words_delta=-deduction,
            words_balance_after=new_remaining,
            event_type="humanize_use",
            reference_id=created.id,
            billing_period=period,
            description=f"Paraphrase request ({req.mode})",
        )
        await word_repo.add_entry(usage_entry)
    else:
        new_remaining = 999999999

    words_per_month_val = words_per_month
    if words_per_month_val == -1:
        quota_pct = 100.0
        total_this_month = 0
    else:
        total_this_month = words_per_month_val - new_remaining
        quota_pct = (new_remaining / words_per_month_val * 100) if words_per_month_val > 0 else 0

    if quota_pct > 50:
        urgency = "good"
    elif quota_pct > 20:
        urgency = "low"
    elif quota_pct > 10:
        urgency = "medium"
    else:
        urgency = "critical"

    return HumanizeResponse(
        humanized=paraphrased_text,
        words_humanized=word_count,
        words_remaining=new_remaining,
        words_total_this_month=total_this_month if words_per_month_val != -1 else None,
        quota_pct_remaining=round(quota_pct, 1),
        quota_urgency=urgency,
        mode_used=f"paraphrase_{req.mode}",
        provider_used=llm_result.get("provider", "unknown"),
        duration_ms=duration_ms,
    )
