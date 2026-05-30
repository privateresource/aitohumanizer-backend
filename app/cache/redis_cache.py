import json
import logging
import time
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

_LOADED_FLAG_KEY = "cache:fully_loaded"

try:
    from upstash_redis.asyncio import Redis as UpstashRedis
except ImportError:
    UpstashRedis = None


class RedisCache:
    def __init__(self):
        self._local_fallback: dict[str, dict] = {}
        self._redis: Optional[Any] = None
        self._available = False
        if UpstashRedis is not None and settings.upstash_redis_url and settings.upstash_redis_token:
            try:
                self._redis = UpstashRedis(
                    url=settings.upstash_redis_url,
                    token=settings.upstash_redis_token,
                )
                self._available = True
            except Exception as e:
                logger.warning("Failed to init Upstash Redis: %s", e)

    def _serialize(self, value: Any) -> str:
        return json.dumps(value, default=str)

    def _deserialize(self, raw: Optional[str]) -> Optional[Any]:
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    async def set(self, key: str, value: Any, ex: Optional[int] = None) -> None:
        serialized = self._serialize(value)
        if self._available:
            try:
                if ex:
                    await self._redis.setex(key, ex, serialized)
                else:
                    await self._redis.set(key, serialized)
                return
            except Exception as e:
                logger.warning("Redis set failed for '%s': %s", key, e)
        self._local_fallback[key] = {"value": value, "loaded_at": time.time()}

    async def get(self, key: str) -> Optional[Any]:
        if self._available:
            try:
                raw = await self._redis.get(key)
                if raw is not None:
                    return self._deserialize(raw)
            except Exception as e:
                logger.warning("Redis get failed for '%s': %s", key, e)
        entry = self._local_fallback.get(key)
        return entry["value"] if entry else None

    async def delete(self, key: str) -> None:
        if self._available:
            try:
                await self._redis.delete(key)
            except Exception as e:
                logger.warning("Redis delete failed for '%s': %s", key, e)
        self._local_fallback.pop(key, None)

    async def clear(self) -> None:
        if self._available:
            try:
                cursor = "0"
                deleted = 0
                while True:
                    result = await self._redis.scan(cursor)
                    cursor = str(result[0])
                    keys = result[1] if len(result) > 1 else []
                    if keys:
                        await self._redis.delete(*keys)
                        deleted += len(keys)
                    if cursor == "0":
                        break
                logger.info("Redis cache cleared (%d keys)", deleted)
            except Exception as e:
                logger.warning("Redis clear failed: %s", e)
        self._local_fallback.clear()

    async def clear_prefix(self, prefix: str) -> None:
        if self._available:
            try:
                cursor = "0"
                deleted = 0
                while True:
                    result = await self._redis.scan(cursor, match=f"{prefix}*")
                    cursor = str(result[0])
                    keys = result[1] if len(result) > 1 else []
                    if keys:
                        await self._redis.delete(*keys)
                        deleted += len(keys)
                    if cursor == "0":
                        break
                logger.info("Cleared %d keys with prefix '%s'", deleted, prefix)
            except Exception as e:
                logger.warning("Redis clear_prefix failed for '%s': %s", prefix, e)
        self._local_fallback = {k: v for k, v in self._local_fallback.items() if not k.startswith(prefix)}

    async def load_all_plans(self) -> None:
        import app.db.neon
        pool = app.db.neon.pool
        if not pool:
            logger.warning("Cannot load cache: DB pool not available")
            return

        from app.cache.cache_keys import (
            ALL_PLANS_KEY, ALL_COUPONS_KEY, PUBLIC_PLANS_KEY,
            SYSTEM_CONFIG_KEY, LLM_PROVIDERS_KEY, LT_SERVERS_KEY,
            plan_key, tool_limits_key, plan_features_key, coupon_key,
        )

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM pricing_plans ORDER BY display_order ASC"
            )

            all_plans = []
            for row in rows:
                d = dict(row)
                d["id"] = str(d["id"])
                val = d.get("max_words_per_month")
                d["max_words_per_month"] = val if val is not None else -1

                tools = await conn.fetch(
                    "SELECT * FROM plan_tool_limits WHERE plan_id = $1 ORDER BY tool",
                    row["id"],
                )
                d["tool_limits"] = [
                    {
                        "id": t["id"],
                        "tool": t["tool"],
                        "max_requests_per_month": t["max_requests_per_month"],
                        "max_requests_per_day": t["max_requests_per_day"],
                        "max_words_per_request": t["max_words_per_request"],
                        "enabled": t["enabled"],
                    }
                    for t in tools
                ]

                features = await conn.fetch(
                    "SELECT * FROM plan_features WHERE plan_id = $1 ORDER BY sort_order ASC, feature_key ASC",
                    row["id"],
                )
                d["features"] = [
                    {
                        "id": f["id"],
                        "feature_key": f["feature_key"],
                        "feature_value": f["feature_value"],
                        "sort_order": f["sort_order"],
                    }
                    for f in features
                ]

                sk = d["slug"]
                await self.set(plan_key(sk), d)
                await self.set(tool_limits_key(sk), d["tool_limits"])
                await self.set(plan_features_key(sk), d["features"])
                all_plans.append(d)

            await self.set(ALL_PLANS_KEY, all_plans)

            public = [p for p in all_plans if p.get("is_active") and p.get("is_public")]
            await self.set(PUBLIC_PLANS_KEY, public)

            coupons = await conn.fetch(
                "SELECT * FROM coupons ORDER BY created_at DESC"
            )
            coupon_list = []
            for c in coupons:
                c_dict = dict(c)
                c_dict["id"] = str(c_dict["id"])
                plan_rows = await conn.fetch(
                    "SELECT plan_slug FROM coupon_plan_limits WHERE coupon_id = $1",
                    c["id"],
                )
                c_dict["plan_names"] = [p["plan_slug"] for p in plan_rows]
                await self.set(coupon_key(c["code"]), c_dict)
                coupon_list.append(c_dict)

            await self.set(ALL_COUPONS_KEY, coupon_list)

            try:
                cfg_rows = await conn.fetch("SELECT key, value FROM system_config")
                config_map = {r["key"]: r["value"] for r in cfg_rows}
                await self.set(SYSTEM_CONFIG_KEY, config_map)
            except Exception as e:
                logger.warning("Failed to cache system config: %s", e)

            try:
                provider_rows = await conn.fetch(
                    "SELECT id, name, provider_type, config, is_active, is_default FROM llm_providers"
                )
                providers = [dict(r) for r in provider_rows]
                for p in providers:
                    if isinstance(p.get("config"), str):
                        p["config"] = json.loads(p["config"])
                await self.set(LLM_PROVIDERS_KEY, providers)
            except Exception as e:
                logger.warning("Failed to cache LLM providers: %s", e)

            try:
                lt_row = await conn.fetchrow(
                    "SELECT value FROM system_config WHERE key = 'grammar_checker_servers'"
                )
                if lt_row and lt_row["value"]:
                    parsed = json.loads(lt_row["value"])
                    await self.set(LT_SERVERS_KEY, parsed)
                else:
                    url_row = await conn.fetchrow(
                        "SELECT value FROM system_config WHERE key = 'grammar_checker_api_urls'"
                    )
                    if url_row and url_row["value"]:
                        urls = [u.strip() for u in url_row["value"].split(",") if u.strip()]
                        await self.set(LT_SERVERS_KEY, [{"url": u, "apiKey": ""} for u in urls])
                    else:
                        await self.set(LT_SERVERS_KEY, [])
            except Exception as e:
                logger.warning("Failed to cache LanguageTool servers: %s", e)

            if self._available:
                try:
                    await self._redis.set(_LOADED_FLAG_KEY, "1")
                except Exception:
                    pass
            logger.info("Cache fully loaded: plans=%d coupons=%d", len(all_plans), len(coupon_list))

    async def get_or_load(self, key: str) -> Optional[Any]:
        loaded = False
        if self._available:
            try:
                flag = await self._redis.get(_LOADED_FLAG_KEY)
                loaded = flag == "1"
            except Exception:
                pass
        if not loaded:
            logger.info("Cache cold — reloading from Neon")
            await self.load_all_plans()
        return await self.get(key)

    def stats(self) -> dict:
        return {
            "cache_type": "upstash_redis" if self._available else "local_fallback",
            "available": self._available,
            "local_fallback_keys": len(self._local_fallback),
        }
