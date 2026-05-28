from typing import Optional
from pydantic import BaseModel


class ContentBlock(BaseModel):
    type: str
    text: str


class Message(BaseModel):
    id: str
    type: str
    role: str
    content: list[ContentBlock]
    model: str
    stop_reason: Optional[str] = None
    stop_sequence: Optional[str] = None
    usage: Optional["Usage"] = None


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class AnthropicMessageRequest(BaseModel):
    model: str
    max_tokens: int = 1024
    temperature: float = 0.7
    system: Optional[str] = None
    messages: list["RequestMessage"]


class RequestMessage(BaseModel):
    role: str
    content: str


class AnthropicMessageResponse(BaseModel):
    id: str
    type: str
    role: str
    content: list[ContentBlock]
    model: str
    stop_reason: Optional[str] = None
    stop_sequence: Optional[str] = None
    usage: Usage


class ErrorResponse(BaseModel):
    type: str
    error: dict
