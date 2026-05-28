import time
from typing import Optional

import httpx

from app.llm.providers.base_provider import BaseLLMProvider, LLMRequest, LLMResponse
from app.llm.providers.openai_compatible.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
)

DEFAULT_TIMEOUT = 30


class OpenAICompatibleProvider(BaseLLMProvider):
    def __init__(self, provider_id: str, config: dict):
        super().__init__(provider_id, config)
        self.base_url = config.get("base_url", "https://api.openai.com/v1").rstrip("/")
        self.default_model = config.get("default_model", "gpt-4o-mini")
        self.max_input_chars = config.get("max_input_chars", 12000)

    async def humanize(self, request: LLMRequest, api_key: str) -> LLMResponse:
        start = time.monotonic()
        model = request.model or self.default_model
        timeout = request.timeout or DEFAULT_TIMEOUT

        user_prompt = request.user_prompt
        if len(user_prompt) > self.max_input_chars:
            user_prompt = user_prompt[: self.max_input_chars] + "\n\n[INPUT TRUNCATED]"

        payload = ChatCompletionRequest(
            model=model,
            messages=[
                ChatMessage(role="system", content=request.system_prompt),
                ChatMessage(role="user", content=user_prompt),
            ],
            max_tokens=request.max_tokens,
            temperature=request.temperature,
        )

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload.model_dump(exclude_none=True),
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as e:
            elapsed = int((time.monotonic() - start) * 1000)
            return LLMResponse(
                text="",
                model=model,
                provider=self.provider_id,
                duration_ms=elapsed,
                error=f"Request timed out after {timeout}s: {e}",
            )
        except httpx.HTTPStatusError as e:
            elapsed = int((time.monotonic() - start) * 1000)
            detail = ""
            try:
                detail = e.response.json().get("error", {}).get("message", str(e))
            except Exception:
                detail = str(e)
            return LLMResponse(
                text="",
                model=model,
                provider=self.provider_id,
                duration_ms=elapsed,
                error=f"HTTP {e.response.status_code}: {detail}",
            )
        except Exception as e:
            elapsed = int((time.monotonic() - start) * 1000)
            return LLMResponse(
                text="",
                model=model,
                provider=self.provider_id,
                duration_ms=elapsed,
                error=str(e),
            )

        parsed = ChatCompletionResponse(**data)
        elapsed = int((time.monotonic() - start) * 1000)
        text = parsed.choices[0].message.content if parsed.choices else ""
        tokens = parsed.usage.total_tokens if parsed.usage else 0

        return LLMResponse(
            text=text,
            model=parsed.model,
            provider=self.provider_id,
            duration_ms=elapsed,
            tokens_used=tokens,
        )

    async def test_connection(self, api_key: str) -> bool:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10)) as client:
                response = await client.get(
                    f"{self.base_url}/models",
                    headers=headers,
                )
                return response.status_code == 200
        except Exception:
            return False
