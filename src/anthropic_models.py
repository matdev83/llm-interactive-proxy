"""
Pydantic models for Anthropic API request/response structures.
"""
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


class AnthropicMessage(BaseModel):
    """Represents a message in the Anthropic API."""
    role: str
    content: Union[str, List[Dict[str, Any]]]


class AnthropicMessagesRequest(BaseModel):
    """Represents a request to the Anthropic Messages API."""
    model: str
    messages: List[AnthropicMessage]
    system: Optional[str] = None
    max_tokens: int
    metadata: Optional[Dict[str, Any]] = None
    stop_sequences: Optional[List[str]] = Field(default=None, alias="stop_sequences")
    stream: Optional[bool] = False
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None


class ContentBlock(BaseModel):
    """Represents a content block in an Anthropic message."""
    type: str
    text: str


class ToolUseBlock(BaseModel):
    """Represents a tool invocation block in Anthropic messages."""

    type: str = "tool_use"
    id: Optional[str] = None
    name: Optional[str] = None
    input: Optional[Dict[str, Any]] = None


class Usage(BaseModel):
    """Represents the usage statistics for a request."""
    input_tokens: int
    output_tokens: int


class AnthropicMessagesResponse(BaseModel):
    """Represents a response from the Anthropic Messages API."""
    id: str
    type: str
    role: str
    content: List[ContentBlock]
    model: str
    stop_reason: Optional[str] = Field(None, alias="stop_reason")
    stop_sequence: Optional[str] = Field(None, alias="stop_sequence")
    usage: Usage