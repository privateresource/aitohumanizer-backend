import time
from typing import Optional

import httpx
from anthropic import AsyncAnthropic
from anthropic import APIStatusError, APIError, APITimeoutError

from app.llm.providers.base_provider import BaseLLMProvider, LLMRequest, LLMResponse

DEFAULT_TIMEOUT = 30


class AnthropicProvider(BaseLLMProvider):
    def __init__(self, provider_id: str, config: dict):
        super().__init__(provider_id, config)
        self.default_model = config.get("default_model", "claude-sonnet-4-20250514")
        self.base_url = config.get("base_url", None)

    async def humanize(self, request: LLMRequest, api_key: str) -> LLMResponse:
        start = time.monotonic()
        model = request.model or self.default_model
        timeout = request.timeout or DEFAULT_TIMEOUT

        client_kwargs = {
            "api_key": api_key,
            "max_retries": 0,
            "timeout": httpx.Timeout(timeout),
        }
        if self.base_url:
            client_kwargs["base_url"] = self.base_url

        try:
            client = AsyncAnthropic(**client_kwargs)
            response = await client.messages.create(
                model=model,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                system=request.system_prompt,
                messages=[{"role": "user", "content": request.user_prompt}],
            )
        except APITimeoutError as e:
            elapsed = int((time.monotonic() - start) * 1000)
            return LLMResponse(
                text="",
                model=model,
                provider=self.provider_id,
                duration_ms=elapsed,
                error=f"Request timed out after {timeout}s: {e}",
            )
        except APIStatusError as e:
            elapsed = int((time.monotonic() - start) * 1000)
            return LLMResponse(
                text="",
                model=model,
                provider=self.provider_id,
                duration_ms=elapsed,
                error=f"HTTP {e.status_code}: {e.body}",
            )
        except APIError as e:
            elapsed = int((time.monotonic() - start) * 1000)
            return LLMResponse(
                text="",
                model=model,
                provider=self.provider_id,
                duration_ms=elapsed,
                error=str(e),
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

        elapsed = int((time.monotonic() - start) * 1000)
        text = "".join(block.text for block in response.content if block.type == "text")
        tokens = (response.usage.input_tokens + response.usage.output_tokens) if response.usage else 0

        return LLMResponse(
            text=text,
            model=response.model,
            provider=self.provider_id,
            duration_ms=elapsed,
            tokens_used=tokens,
        )

    async def test_connection(self, api_key: str) -> bool:
        try:
            client = AsyncAnthropic(
                api_key=api_key,
                max_retries=0,
                timeout=httpx.Timeout(10),
            )
            await client.models.list()
            return True
        except Exception:
            return False
