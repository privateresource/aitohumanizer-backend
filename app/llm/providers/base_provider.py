from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LLMRequest:
    system_prompt: str
    user_prompt: str
    model: str
    max_tokens: int = 1024
    temperature: float = 0.7
    timeout: int = 30


@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str
    duration_ms: int
    tokens_used: int = 0
    error: Optional[str] = None


class BaseLLMProvider(ABC):
    def __init__(self, provider_id: str, config: dict):
        self.provider_id = provider_id
        self.config = config

    @abstractmethod
    async def humanize(self, request: LLMRequest, api_key: str) -> LLMResponse:
        pass

    @abstractmethod
    async def test_connection(self, api_key: str) -> bool:
        pass
