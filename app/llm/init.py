import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.cache import cache
from app.llm.keys.key_manager import decrypt_key
from app.llm.providers.base_provider import BaseLLMProvider

logger = logging.getLogger(__name__)

HUMANIZE_MODES = ["standard", "academic", "casual", "turbo"]
PARAPHRASE_MODES = ["standard", "fluency", "formal", "casual", "shorten", "expand"]


async def init_providers(db: AsyncSession) -> None:
    from app.llm.router import set_providers, set_fallback_engine, set_router
    from app.llm.router.llm_router import LLMRouter
    from app.llm.fallback.fallback_engine import FallbackEngine

    cache.clear()

    result = await db.execute(
        text("SELECT * FROM llm_providers WHERE is_active = TRUE ORDER BY created_at DESC")
    )
    rows = result.fetchall()

    providers: dict[str, BaseLLMProvider] = {}
    for row in rows:
        provider_id = str(row.id)
        provider_type = row.provider_type
        config = row.config or {}

        if provider_type == "openai_compatible":
            from app.llm.providers.openai_compatible.provider import OpenAICompatibleProvider
            p = OpenAICompatibleProvider(provider_id, config)
        elif provider_type == "anthropic":
            from app.llm.providers.anthropic.provider import AnthropicProvider
            p = AnthropicProvider(provider_id, config)
        else:
            logger.warning("unsupported_provider_type", provider_id=provider_id, provider_type=provider_type)
            continue

        providers[provider_id] = p
        cache.set_provider(provider_id, p)

    try:
        key_result = await db.execute(
            text("SELECT provider_id, encrypted_key, label FROM llm_provider_keys WHERE is_active = TRUE AND is_parked = FALSE")
        )
        for key_row in key_result.fetchall():
            decrypted = decrypt_key(key_row.encrypted_key)
            cache.add_key(str(key_row.provider_id), decrypted, key_row.label or "")
    except Exception:
        logger.warning("no_keys_found", exc_info=True)

    provider_ids = list(providers.keys())
    chains = {}
    for mode in HUMANIZE_MODES + PARAPHRASE_MODES:
        chains[mode] = list(provider_ids)

    fallback_config = {"chains": chains, "max_fallback_depth": len(provider_ids) or 3}

    set_providers(providers)
    if providers:
        engine = FallbackEngine(providers, fallback_config)
        set_fallback_engine(engine)
        set_router(LLMRouter(engine))
        logger.info(
            "llm_providers_initialized",
            provider_count=len(providers),
            chains={k: list(v) for k, v in chains.items()},
        )
    else:
        logger.warning("no_active_providers_found")
