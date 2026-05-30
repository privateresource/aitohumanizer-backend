import asyncio
import json
import logging
import time
from typing import Any, Optional

import app.db.neon
from app.cache.cache_keys import (
    ALL_PLANS_KEY, PUBLIC_PLANS_KEY, ALL_COUPONS_KEY,
    SYSTEM_CONFIG_KEY, LLM_PROVIDERS_KEY, LT_SERVERS_KEY,
    plan_key, tool_limits_key, plan_features_key, coupon_key,
)

logger = logging.getLogger(__name__)


class LocalCache:
    def __init__(self):
        self._store: dict[str, dict] = {}
        self._lock = asyncio.Lock()
        self._is_loaded = False

    async def set(self, key: str, value: Any) -> None:
        async with self._lock:
            self._store[key] = {
                "value": value,
                "loaded_at": time.time(),
            }

    async def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            return None
        return entry["value"]

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()
            self._is_loaded = False
            logger.info("Local cache cleared")

    async def clear_prefix(self, prefix: str) -> None:
        async with self._lock:
            to_delete = [k for k in self._store if k.startswith(prefix)]
            for key in to_delete:
                del self._store[key]
            logger.info(f"Cleared %d keys with prefix '%s'", len(to_delete), prefix)

    async def load_all_plans(self) -> None:
        pool = app.db.neon.pool
        if not pool:
            logger.warning("Cannot load cache: DB pool not available")
            return

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

            # ── System config ──
            try:
                cfg_rows = await conn.fetch("SELECT key, value FROM system_config")
                config_map = {r["key"]: r["value"] for r in cfg_rows}
                await self.set(SYSTEM_CONFIG_KEY, config_map)
            except Exception as e:
                logger.warning("Failed to cache system config: %s", e)

            # ── LLM providers ──
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

            # ── LanguageTool servers ──
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

            self._is_loaded = True
            logger.info("Cache fully loaded: plans=%d coupons=%d config=%d llm=%d",
                         len(all_plans), len(coupon_list),
                         len(config_map), len(providers))

    async def get_or_load(self, key: str) -> Optional[Any]:
        if not self._is_loaded:
            logger.info("Cache empty — reloading from Neon")
            await self.load_all_plans()
        return await self.get(key)

    def stats(self) -> dict:
        return {
            "total_keys": len(self._store),
            "is_loaded": self._is_loaded,
            "keys": list(self._store.keys()),
        }
