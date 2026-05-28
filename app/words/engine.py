from datetime import datetime
from uuid import UUID

class WordQuotaEngine:

    async def get_balance(self, user_id: UUID, db) -> int:
        """Sum word_usage.words_delta for user. Unlimited plan returns -1."""
        plan = await self.get_user_plan(user_id, db)
        if plan.get("words_per_month") == -1:
            return -1
        row = await db.fetchrow(
            "SELECT COALESCE(SUM(words_delta), 0) AS balance FROM word_usage WHERE user_id = $1",
            user_id
        )
        return max(0, row["balance"])

    async def get_user_plan(self, user_id: UUID, db) -> dict:
        """Get user's current plan with word limits."""
        row = await db.fetchrow("""
            SELECT p.* FROM plans p
            JOIN subscriptions s ON s.plan_id = p.id
            WHERE s.user_id = $1 AND s.status = 'active'
        """, user_id)
        if not row:
            # Default to free plan
            row = await db.fetchrow("SELECT * FROM plans WHERE slug = 'free'")
        return dict(row)

    async def check_sufficient(self, user_id: UUID, words: int, db) -> bool:
        balance = await self.get_balance(user_id, db)
        if balance == -1:
            return True
        return balance >= words

    async def deduct(self, user_id: UUID, words: int, request_id: UUID, db) -> int:
        balance = await self.get_balance(user_id, db)
        if balance == -1:
            return -1
        new_balance = balance - words
        period = datetime.now().strftime("%Y-%m")
        await db.execute("""
            INSERT INTO word_usage
            (user_id, words_delta, words_balance_after, event_type, reference_id, billing_period)
            VALUES ($1, $2, $3, 'humanize_use', $4, $5)
        """, user_id, -words, new_balance, request_id, period)
        return new_balance

    async def grant(self, user_id: UUID, words: int, event_type: str, db, reference_id=None, description=""):
        balance = await self.get_balance(user_id, db)
        if balance == -1:
            period = datetime.now().strftime("%Y-%m")
            await db.execute("""
                INSERT INTO word_usage (user_id, words_delta, words_balance_after, event_type, reference_id, billing_period, description)
                VALUES ($1, 0, -1, $2, $3, $4, $5)
            """, user_id, event_type, reference_id, period, description)
            return
        new_balance = balance + words
        period = datetime.now().strftime("%Y-%m")
        await db.execute("""
            INSERT INTO word_usage (user_id, words_delta, words_balance_after, event_type, reference_id, billing_period, description)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """, user_id, words, new_balance, event_type, reference_id, period, description)

    async def monthly_reset(self, db):
        rows = await db.fetch("""
            SELECT s.user_id, p.words_per_month, p.slug as plan_slug
            FROM subscriptions s
            JOIN plans p ON s.plan_id = p.id
            WHERE s.status = 'active'
            AND s.current_period_end <= NOW()
        """)
        for row in rows:
            user_id = row["user_id"]
            if row["words_per_month"] == -1:
                continue
            current_balance = await self.get_balance(user_id, db)
            if current_balance > 0 and row["plan_slug"] != "free":
                await self.grant(user_id, -current_balance, "expiry", db, description="Monthly reset - unused words expired")
            await self.grant(user_id, row["words_per_month"], "monthly_grant", db)

word_quota_engine = WordQuotaEngine()
