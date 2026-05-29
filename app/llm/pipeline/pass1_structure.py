from app.llm.fallback.fallback_engine import FallbackEngine
from app.llm.providers.base_provider import LLMRequest, LLMResponse
from app.llm.prompts.prompt_builder import build_pass_system_prompt, build_pass_user_prompt
from app.llm.prompts.pass_temperatures import get_pass_temperature


async def run_pass1(
    fallback: FallbackEngine,
    text: str,
    chain_type: str,
    max_tokens: int,
    preferred_provider_id: str = None,
) -> LLMResponse:
    system = build_pass_system_prompt(1)
    user = build_pass_user_prompt(1, text)

    req = LLMRequest(
        system_prompt=system,
        user_prompt=user,
        model="",
        max_tokens=max_tokens,
        temperature=get_pass_temperature(1),
        timeout=120,
    )

    return await fallback.humanize_with_fallback(request=req, chain_type=chain_type, preferred_provider_id=preferred_provider_id)
