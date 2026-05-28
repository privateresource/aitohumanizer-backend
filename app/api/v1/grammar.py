import json
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import httpx

from app.api.deps import get_db_session, get_current_user
from app.cache import cache as cache_store
from app.core.exceptions import BadRequestException, ForbiddenException, QuotaExceededException
from app.db.models.user import User
from app.pricing.usage import check_tool_limit, increment_usage
from app.db.repositories.subscription_repo import SubscriptionRepository
from app.db.repositories.plan_repo import PlanRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/grammar", tags=["grammar"])


class GrammarCheckRequest(BaseModel):
    text: str
    language: str = "en-US"


class GrammarIssueItem(BaseModel):
    id: str
    message: str
    shortMessage: str
    offset: int
    length: int
    replacements: list[str]
    ruleId: str
    ruleDescription: str
    issueType: str
    category: str
    contextText: str
    contextOffset: int
    contextLength: int


class GrammarCheckResponse(BaseModel):
    issues: list[GrammarIssueItem]


@router.post("/check", response_model=GrammarCheckResponse)
async def grammar_check(
    req: GrammarCheckRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    word_count = len(req.text.split())
    if word_count == 0:
        raise BadRequestException(message="Text is empty")

    sub_repo = SubscriptionRepository(session)
    sub = await sub_repo.get_by_user(current_user.id)

    if sub:
        if sub.status not in ("active", "trialing"):
            raise ForbiddenException(
                message="Subscription is not active",
                detail={"status": sub.status},
            )
        plan_repo = PlanRepository(session)
        plan = await plan_repo.get_by_id(sub.plan_id)
        if plan:
            limit_check = await check_tool_limit(session, current_user.id, "grammar_check", plan.id)
            if not limit_check.get("allowed"):
                reason = limit_check.get("reason", "tool_disabled")
                if reason == "monthly_limit_reached":
                    raise QuotaExceededException(message="Grammar check monthly limit reached")
                raise BadRequestException(message=f"Grammar check not available: {reason}")

    servers = await _get_grammar_servers(session)
    if not servers:
        raise BadRequestException(message="No LanguageTool servers configured. Add one in Admin > System.")

    last_error = None
    for server in servers:
        try:
            issues = await _call_languagetool(server["url"], server.get("apiKey", ""), req.text, req.language)
            try:
                await increment_usage(session, current_user.id, "grammar_check", word_count)
            except Exception as e:
                logger.warning("Failed to increment grammar usage: %s", e)
            return GrammarCheckResponse(issues=issues)
        except Exception as e:
            last_error = e
            logger.warning("LanguageTool server %s failed: %s", server["url"], e)
            continue

    raise BadRequestException(
        message="All LanguageTool servers failed",
        detail={"last_error": str(last_error)},
    )


async def _get_grammar_servers(session: AsyncSession) -> list[dict]:
    cached = await cache_store.get("languagetool:servers")
    if cached is not None:
        return [
            {"url": s["url"].rstrip("/"), "apiKey": s.get("apiKey", "")}
            for s in cached if s.get("url")
        ]

    try:
        result = await session.execute(
            text("SELECT value FROM system_config WHERE key = 'grammar_checker_servers'")
        )
        row = result.fetchone()
        if row and row[0]:
            parsed = json.loads(row[0])
            if isinstance(parsed, list) and len(parsed) > 0:
                await cache_store.set("languagetool:servers", parsed)
                return [
                    {"url": s["url"].rstrip("/"), "apiKey": s.get("apiKey", "")}
                    for s in parsed if s.get("url")
                ]
    except Exception:
        pass

    try:
        result = await session.execute(
            text("SELECT value FROM system_config WHERE key = 'grammar_checker_api_urls'")
        )
        row = result.fetchone()
        if row and row[0]:
            urls = [u.strip() for u in row[0].split(",") if u.strip()]
            key_result = await session.execute(
                text("SELECT value FROM system_config WHERE key = 'grammar_checker_api_key'")
            )
            key_row = key_result.fetchone()
            api_key = key_row[0] if key_row else ""
            servers = [{"url": u.rstrip("/"), "apiKey": api_key} for u in urls]
            await cache_store.set("languagetool:servers", servers)
            return servers
    except Exception:
        pass

    return []


async def _call_languagetool(url: str, api_key: str, text: str, language: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=30) as client:
        body = {"text": text, "language": language}
        if api_key:
            body["apiKey"] = api_key

        response = await client.post(
            f"{url}/v2/check",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        data = response.json()

        issues = []
        for i, match in enumerate(data.get("matches", [])):
            issues.append({
                "id": f"lt-{i}",
                "message": match.get("message", ""),
                "shortMessage": match.get("shortMessage", ""),
                "offset": match.get("offset", 0),
                "length": match.get("length", 0),
                "replacements": [r["value"] for r in match.get("replacements", [])],
                "ruleId": match.get("rule", {}).get("id", ""),
                "ruleDescription": match.get("rule", {}).get("description", ""),
                "issueType": match.get("rule", {}).get("issueType", ""),
                "category": match.get("rule", {}).get("category", {}).get("name", ""),
                "contextText": match.get("context", {}).get("text", ""),
                "contextOffset": match.get("context", {}).get("offset", 0),
                "contextLength": match.get("context", {}).get("length", 0),
            })

        return issues
