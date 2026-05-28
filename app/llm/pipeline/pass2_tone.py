import random

from app.llm.fallback.fallback_engine import FallbackEngine
from app.llm.providers.base_provider import LLMRequest
from app.llm.prompts.prompt_builder import build_pass_system_prompt, build_pass2_user_prompt
from app.llm.prompts.pass_temperatures import get_pass_temperature

STYLE_VARIANTS = [
    "Write with a confident, direct tone — like someone who knows their stuff but isn't showing off.",
    "Write with a warm, slightly informal tone — like a smart colleague explaining something over coffee.",
    "Write with a thoughtful, measured tone — like an experienced professional who chooses words carefully.",
    "Write conversationally but with depth — like a blogger who actually knows the subject well.",
]


def _get_random_style() -> str:
    return random.choice(STYLE_VARIANTS)


async def run_pass2(
    fallback: FallbackEngine,
    text: str,
    chain_type: str,
    max_tokens: int,
) -> str:
    system = build_pass_system_prompt(2)
    style = _get_random_style()
    user = build_pass2_user_prompt(text, style)

    req = LLMRequest(
        system_prompt=system,
        user_prompt=user,
        model="",
        max_tokens=max_tokens,
        temperature=get_pass_temperature(2),
        timeout=60,
    )

    resp = await fallback.humanize_with_fallback(request=req, chain_type=chain_type)
    return resp.text or ""
