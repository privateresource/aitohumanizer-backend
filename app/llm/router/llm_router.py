import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.fallback.fallback_engine import FallbackEngine
from app.llm.pipeline.engine import run_pipeline
from app.llm.prompts.prompt_builder import build_paraphraser_prompt
from app.llm.prompts.paraphraser_temps import get_paraphrase_temperature
from app.llm.providers.base_provider import LLMRequest
from app.llm.utils.logger import logger
from app.llm.utils.sanitizer import sanitize_input, clean_llm_output


BUILT_IN_MOODS: dict[str, str] = {
    "neutral": "No specific tone adjustment.",
    "confident": "Direct, assertive, no hedging.",
    "casual": "Relaxed, conversational, like texting a friend.",
    "formal": "Polished, structured, professional distance.",
    "storytelling": "Narrative flow, engaging, scene-setting.",
    "persuasive": "Compelling, rhetorical, conviction-driven.",
}


async def resolve_mood_prompt(mood: Optional[str], user_id: Optional[str], db: Optional[AsyncSession]) -> str:
    if not mood:
        return ""
    if mood in BUILT_IN_MOODS:
        return BUILT_IN_MOODS[mood]
    if db and user_id:
        from sqlalchemy import text
        result = await db.execute(
            text("SELECT prompt FROM user_moods WHERE id = :id AND user_id = :uid"),
            {"id": mood, "uid": user_id},
        )
        row = result.fetchone()
        if row:
            return row.prompt
    return mood


class LLMRouter:
    def __init__(self, fallback_engine: FallbackEngine):
        self._fallback = fallback_engine

    async def route_humanize(
        self,
        text: str,
        mode: str = "standard",
        user_id: Optional[str] = None,
        preferred_provider_id: Optional[str] = None,
        db: Optional[AsyncSession] = None,
        mood: Optional[str] = None,
    ) -> dict:
        import time
        sanitized = sanitize_input(text)
        mood_prompt = await resolve_mood_prompt(mood, user_id, db)

        start = time.monotonic()
        pipeline_result = await run_pipeline(
            fallback=self._fallback,
            text=sanitized,
            chain_type=mode,
            preferred_provider_id=preferred_provider_id,
            mood_prompt=mood_prompt,
        )
        total_elapsed = int((time.monotonic() - start) * 1000)

        final_text = pipeline_result.get("humanized_text", "")
        passes = pipeline_result.get("passes_completed", 0)

        if not final_text:
            error_detail = pipeline_result.get("error") or "All LLM passes returned empty"
            logger.error(
                "humanize_all_passes_failed",
                mode=mode,
                user_id=user_id,
                error=error_detail,
                passes_completed=passes,
            )
            return {
                "humanized_text": "",
                "model": "",
                "provider": "fallback",
                "duration_ms": total_elapsed,
                "tokens_used": 0,
                "error": error_detail,
                "mode": mode,
            }

        result = {
            "humanized_text": final_text,
            "model": "",
            "provider": "pipeline",
            "duration_ms": total_elapsed,
            "tokens_used": 0,
            "error": None,
            "mode": mode,
            "passes_completed": passes,
        }

        logger.info(
            "humanize_succeeded",
            mode=mode,
            passes=passes,
            duration_ms=total_elapsed,
            user_id=user_id,
        )

        if db and user_id:
            await self._record_request(db, user_id, text, final_text, mode, total_elapsed)

        return result

    async def route_paraphrase(
        self,
        text: str,
        mode: str = "standard",
        user_id: Optional[str] = None,
        preferred_provider_id: Optional[str] = None,
        db: Optional[AsyncSession] = None,
        mood: Optional[str] = None,
    ) -> dict:
        sanitized = sanitize_input(text)
        mood_prompt = await resolve_mood_prompt(mood, user_id, db)

        system_prompt = build_paraphraser_prompt(mode)
        if mood_prompt:
            system_prompt += f"\n\nMOOD: {mood_prompt}"

        max_tokens = min(max(len(sanitized.split()) * 2, 256), 4096)
        temperature = get_paraphrase_temperature(mode)

        request = LLMRequest(
            system_prompt=system_prompt,
            user_prompt=sanitized,
            model="",
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=60,
        )

        import time
        start = time.monotonic()
        response = await self._fallback.humanize_with_fallback(
            request=request,
            chain_type=mode,
            preferred_provider_id=preferred_provider_id,
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)

        cleaned = clean_llm_output(response.text) if response.text else ""
        result = {
            "humanized_text": cleaned,
            "model": response.model,
            "provider": response.provider,
            "duration_ms": response.duration_ms or elapsed_ms,
            "tokens_used": response.tokens_used,
            "error": response.error,
            "mode": mode,
        }

        if response.error:
            logger.error("paraphrase_failed", mode=mode, error=response.error, user_id=user_id)
        else:
            logger.info(
                "paraphrase_succeeded",
                mode=mode,
                provider=response.provider,
                model=response.model,
                tokens=response.tokens_used,
                duration_ms=elapsed_ms,
                user_id=user_id,
            )

        if db and user_id:
            await self._record_request(db, user_id, text, response.text or text, mode, elapsed_ms)

        return result

    async def _record_request(
        self,
        db: AsyncSession,
        user_id: str,
        input_text: str,
        output_text: str,
        mode: str,
        duration_ms: int = 0,
    ) -> None:
        from app.db.models.humanize_request import HumanizeRequest

        record = HumanizeRequest(
            user_id=uuid.UUID(user_id) if user_id else None,
            input_text=input_text,
            output_text=output_text,
            mode=mode,
            word_count=len(input_text.split()),
            tokens_used=0,
            processing_time_ms=duration_ms,
            status="completed",
            ai_model=f"pipeline/{mode}",
        )
        db.add(record)
        await db.commit()
