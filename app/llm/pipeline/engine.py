from app.llm.fallback.fallback_engine import FallbackEngine
from app.llm.pipeline.pass1_structure import run_pass1
from app.llm.pipeline.pass2_tone import run_pass2
from app.llm.pipeline.pass3_polish import run_pass3
from app.llm.utils.logger import logger
from app.llm.utils.sanitizer import clean_llm_output


def _calc_max_tokens(text: str) -> int:
    return min(max(len(text.split()) * 2, 256), 4096)


async def run_pipeline(
    fallback: FallbackEngine,
    text: str,
    chain_type: str,
) -> dict:
    max_tok = _calc_max_tokens(text)

    p1 = await run_pass1(fallback, text, chain_type, max_tok)
    if not p1:
        return {"humanized_text": "", "passes_completed": 0}

    p2 = await run_pass2(fallback, p1, chain_type, max_tok)
    if not p2:
        cleaned = clean_llm_output(p1)
        return {"humanized_text": cleaned, "passes_completed": 1}

    p3 = await run_pass3(fallback, p2, chain_type, max_tok)
    if not p3:
        cleaned = clean_llm_output(p2)
        return {"humanized_text": cleaned, "passes_completed": 2}

    cleaned = clean_llm_output(p3)
    return {"humanized_text": cleaned, "passes_completed": 3}