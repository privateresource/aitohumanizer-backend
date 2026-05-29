from datetime import date
from uuid import UUID
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import cache
from app.cache.cache_keys import tool_limits_key, plan_features_key


async def get_user_usage(
    session: AsyncSession,
    user_id: UUID,
    tool: str,
    period_start: date,
) -> dict:
    result = await session.execute(
        text("""
            SELECT requests_used, words_used
            FROM user_usage
            WHERE user_id = :uid AND tool = :tool AND period_start = :ps
        """),
        {"uid": user_id, "tool": tool, "ps": period_start},
    )
    row = result.fetchone()
    if row:
        return {"requests_used": row.requests_used, "words_used": row.words_used}
    return {"requests_used": 0, "words_used": 0}


async def increment_usage(
    session: AsyncSession,
    user_id: UUID,
    tool: str,
    words: int,
):
    period_start, period_end = _get_billing_period()
    await session.execute(
        text("""
            INSERT INTO user_usage (user_id, tool, period_start, period_end, requests_used, words_used)
            VALUES (:uid, :tool, :ps, :pe, 1, :words)
            ON CONFLICT (user_id, tool, period_start)
            DO UPDATE SET
                requests_used = user_usage.requests_used + 1,
                words_used = user_usage.words_used + :words2,
                updated_at = NOW()
        """),
        {"uid": user_id, "tool": tool, "ps": period_start, "pe": period_end, "words": words, "words2": words},
    )
    await session.commit()


def _get_billing_period() -> tuple[date, date]:
    from datetime import datetime, timezone
    import calendar

    now = datetime.now(timezone.utc)
    year = now.year
    month = now.month
    _, last_day = calendar.monthrange(year, month)
    return (
        date(year, month, 1),
        date(year, month, last_day),
    )


async def check_tool_limit(
    session: AsyncSession,
    user_id: UUID,
    tool: str,
    plan_id: int,
) -> dict:
    period_start, _ = _get_billing_period()

    result = await session.execute(
        text("""
            SELECT max_requests_per_month, max_requests_per_day, max_words_per_request, enabled
            FROM plan_tool_limits
            WHERE plan_id = :pid AND tool = :tool
        """),
        {"pid": plan_id, "tool": tool},
    )
    limits = result.fetchone()

    if not limits or not limits.enabled:
        return {"allowed": False, "reason": "tool_disabled"}

    usage = await get_user_usage(session, user_id, tool, period_start)

    if limits.max_requests_per_month != -1 and usage["requests_used"] >= limits.max_requests_per_month:
        return {"allowed": False, "reason": "monthly_limit_reached"}

    plan_result = await session.execute(
        text("SELECT max_words_per_month FROM pricing_plans WHERE id = :pid"),
        {"pid": plan_id},
    )
    plan_row = plan_result.fetchone()
    max_words_per_month = plan_row.max_words_per_month if plan_row else -1

    if max_words_per_month != -1:
        total_result = await session.execute(
            text("""
                SELECT COALESCE(SUM(words_used), 0) AS total_words
                FROM user_usage
                WHERE user_id = :uid AND period_start = :ps
            """),
            {"uid": user_id, "ps": period_start},
        )
        total_words = total_result.fetchone().total_words
        if total_words >= max_words_per_month:
            return {"allowed": False, "reason": "monthly_word_limit_reached"}

    return {
        "allowed": True,
        "limits": {
            "max_requests_per_month": limits.max_requests_per_month,
            "max_words_per_request": limits.max_words_per_request,
            "max_words_per_month": max_words_per_month,
        },
        "usage": usage,
    }


async def get_plan_tool_limits(session: AsyncSession, plan_id: int, plan_slug: Optional[str] = None) -> list[dict]:
    if plan_slug:
        cached = await cache.get(tool_limits_key(plan_slug))
        if cached is not None:
            return cached

    result = await session.execute(
        text("""
            SELECT tool, max_requests_per_month, max_requests_per_day, max_words_per_request, enabled
            FROM plan_tool_limits
            WHERE plan_id = :pid
            ORDER BY tool
        """),
        {"pid": plan_id},
    )
    rows = result.fetchall()
    return [
        {
            "tool": r.tool,
            "max_requests_per_month": r.max_requests_per_month,
            "max_requests_per_day": r.max_requests_per_day,
            "max_words_per_request": r.max_words_per_request,
            "enabled": r.enabled,
        }
        for r in rows
    ]


async def get_plan_features(session: AsyncSession, plan_id: int, plan_slug: Optional[str] = None) -> list[dict]:
    if plan_slug:
        cached = await cache.get(plan_features_key(plan_slug))
        if cached is not None:
            return cached

    result = await session.execute(
        text("""
            SELECT feature_key, feature_value, sort_order
            FROM plan_features
            WHERE plan_id = :pid
            ORDER BY sort_order ASC, feature_key ASC
        """),
        {"pid": plan_id},
    )
    rows = result.fetchall()
    return [{"key": r.feature_key, "value": r.feature_value, "sort_order": r.sort_order} for r in rows]


async def get_user_plan_features(session: AsyncSession, user_id: UUID) -> dict[str, str]:
    result = await session.execute(
        text("""
            SELECT pf.feature_key, pf.feature_value
            FROM subscriptions s
            JOIN plans p ON p.id = s.plan_id
            JOIN pricing_plans pp ON pp.legacy_plan_id = p.id
            LEFT JOIN plan_features pf ON pf.plan_id = pp.id
            WHERE s.user_id = :uid AND s.status IN ('active', 'trialing')
        """),
        {"uid": user_id},
    )
    features: dict[str, str] = {}
    rows = result.fetchall()
    if rows:
        for row in rows:
            if row.feature_key:
                features[row.feature_key] = row.feature_value
        return features

    result2 = await session.execute(
        text("""
            SELECT pf.feature_key, pf.feature_value
            FROM pricing_plans pp
            LEFT JOIN plan_features pf ON pf.plan_id = pp.id
            WHERE pp.is_free = true
        """),
    )
    for row in result2.fetchall():
        if row.feature_key:
            features[row.feature_key] = row.feature_value
    return features
