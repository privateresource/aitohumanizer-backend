from app.llm.cache import cache
from app.llm.providers.base_provider import BaseLLMProvider, LLMRequest, LLMResponse
from app.llm.response_cache import llm_response_cache
from app.llm.utils.logger import logger


class FallbackEngine:
    def __init__(self, providers: dict[str, BaseLLMProvider], config: dict):
        self._providers = providers
        self._chains: dict[str, list[str]] = config.get("chains", {})
        self.max_fallback_depth = config.get("max_fallback_depth", 3)

    async def humanize_with_fallback(
        self,
        request: LLMRequest,
        chain_type: str,
        preferred_provider_id: str = None,
    ) -> LLMResponse:
        chain = self._chains.get(chain_type, list(self._providers.keys()))
        attempts = 0
        errors: list[str] = []

        if preferred_provider_id:
            if preferred_provider_id in self._providers:
                chain = [preferred_provider_id] + [p for p in chain if p != preferred_provider_id]
            else:
                logger.warning("preferred_provider_not_found", provider_id=preferred_provider_id)
                errors.append(f"{preferred_provider_id}: provider not found")

        cached = llm_response_cache.get(request.user_prompt, chain_type)
        if cached is not None:
            logger.info("response_cache_hit", chain_type=chain_type)
            return LLMResponse(
                text=cached,
                model="",
                provider="cache",
                duration_ms=0,
            )

        for provider_id in chain:
            if attempts >= self.max_fallback_depth:
                logger.warning("max_fallback_depth_reached", chain_type=chain_type, depth=attempts)
                break

            provider = self._providers.get(provider_id)
            if not provider:
                logger.warning("provider_not_found", provider_id=provider_id)
                errors.append(f"{provider_id}: provider not found")
                continue

            api_key = cache.get_active_key(provider_id)
            if not api_key:
                logger.warning("no_active_key", provider_id=provider_id)
                errors.append(f"{provider_id}: no active API key")
                continue

            response = await provider.humanize(request, api_key)
            attempts += 1

            if response.error:
                logger.error(
                    "provider_failed",
                    provider_id=provider_id,
                    error=response.error,
                    attempt=attempts,
                    model=request.model,
                    base_url=getattr(provider, "base_url", "unknown"),
                )
                errors.append(f"{provider_id}: {response.error}")
                cache.record_failure(provider_id)
                continue

            if not response.text:
                logger.warning(
                    "provider_returned_empty",
                    provider_id=provider_id,
                    attempt=attempts,
                    model=request.model,
                    base_url=getattr(provider, "base_url", "unknown"),
                )
                errors.append(f"{provider_id}: returned empty response")
                cache.record_failure(provider_id)
                continue

            cache.reset_failures(provider_id)
            llm_response_cache.set(request.user_prompt, chain_type, response.text)
            return response

        error_detail = "; ".join(errors) if errors else "All providers exhausted"
        return LLMResponse(
            text="",
            model=request.model,
            provider="fallback",
            duration_ms=0,
            error=error_detail,
        )
