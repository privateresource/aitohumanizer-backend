import logging

logger = logging.getLogger(__name__)

async def get_plan_quota(plan_slug: str, db) -> dict:
    row = await db.fetchrow("SELECT * FROM plans WHERE slug = $1", plan_slug)
    if not row:
        return {"words_per_month": 500, "words_per_request": 200}
    return {
        "words_per_month": row["words_per_month"],
        "words_per_request": row["words_per_request"],
        "modes": row["modes"],
    }

def format_quota_display(words_per_month: int) -> str:
    if words_per_month == -1:
        return "Unlimited"
    if words_per_month >= 1000000:
        return f"{words_per_month // 1000000}M words/month"
    if words_per_month >= 1000:
        return f"{words_per_month // 1000}K words/month"
    return f"{words_per_month} words/month"
