from typing import Optional
from app.llm.router.llm_router import LLMRouter
from app.llm.fallback.fallback_engine import FallbackEngine
from app.llm.providers.base_provider import BaseLLMProvider

_providers: dict[str, BaseLLMProvider] = {}
_engine: Optional[FallbackEngine] = None
_router: Optional[LLMRouter] = None


def get_providers() -> dict[str, BaseLLMProvider]:
    return _providers


def set_providers(providers: dict[str, BaseLLMProvider]):
    global _providers, _engine, _router
    _providers = providers
    _engine = None
    _router = None


def get_fallback_engine() -> Optional[FallbackEngine]:
    return _engine


def set_fallback_engine(engine: FallbackEngine):
    global _engine, _router
    _engine = engine
    _router = None


def get_router() -> Optional[LLMRouter]:
    return _router


def set_router(router: LLMRouter):
    global _router
    _router = router


async def humanize_text(
    text: str,
    mode: str = "standard",
    preferred_provider_id: str = None,
    db=None,
    user_id: str = None,
) -> dict:
    router = get_router()
    if not router:
        return {"error": "No LLM providers configured. Please add providers in Admin > LLM."}
    return await router.route_humanize(
        text=text,
        mode=mode,
        preferred_provider_id=preferred_provider_id,
        db=db,
        user_id=user_id,
    )


async def paraphrase_text(
    text: str,
    mode: str = "standard",
    preferred_provider_id: str = None,
    db=None,
    user_id: str = None,
) -> dict:
    router = get_router()
    if not router:
        return {"error": "No LLM providers configured. Please add providers in Admin > LLM."}
    return await router.route_paraphrase(
        text=text,
        mode=mode,
        preferred_provider_id=preferred_provider_id,
        db=db,
        user_id=user_id,
    )


def get_supported_modes() -> list[str]:
    return ["standard"]


def get_paraphrase_modes() -> list[str]:
    return ["standard", "fluency", "formal", "casual", "shorten", "expand"]


__all__ = [
    "humanize_text", "paraphrase_text",
    "get_supported_modes", "get_paraphrase_modes",
    "get_router", "get_fallback_engine",
    "set_providers", "set_fallback_engine", "set_router",
]