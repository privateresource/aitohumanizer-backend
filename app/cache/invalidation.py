import logging

from app.cache import cache
from app.cache.cache_keys import (
    ALL_PLANS_KEY, PUBLIC_PLANS_KEY, ALL_COUPONS_KEY,
    COUPON_PREFIX, SYSTEM_CONFIG_KEY, LLM_PROVIDERS_KEY, LT_SERVERS_KEY,
)

logger = logging.getLogger(__name__)


async def invalidate_all() -> None:
    """Clear everything. Next get_or_load will reload from Neon."""
    logger.info("Invalidating full cache")
    await cache.clear()


async def invalidate_plan(slug: str) -> None:
    """Clear a single plan and the aggregated lists."""
    await cache.clear_prefix(f"plan:{slug}")
    await cache.delete(ALL_PLANS_KEY)
    await cache.delete(PUBLIC_PLANS_KEY)
    logger.info("Invalidated plan '%s'", slug)


async def invalidate_coupons() -> None:
    """Clear all coupon keys. Next get_or_load will reload everything."""
    await cache.clear_prefix(COUPON_PREFIX)
    await cache.delete(ALL_COUPONS_KEY)
    await cache.delete(ALL_PLANS_KEY)
    await cache.delete(PUBLIC_PLANS_KEY)
    logger.info("Coupon cache invalidated")


async def invalidate_system_config() -> None:
    """Clear system config cache."""
    await cache.delete(SYSTEM_CONFIG_KEY)
    logger.info("System config cache invalidated")


async def invalidate_llm_providers() -> None:
    """Clear LLM provider cache."""
    await cache.delete(LLM_PROVIDERS_KEY)
    logger.info("LLM provider cache invalidated")


async def invalidate_lt_servers() -> None:
    """Clear LanguageTool server cache."""
    await cache.delete(LT_SERVERS_KEY)
    logger.info("LanguageTool server cache invalidated")
