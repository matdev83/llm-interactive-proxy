from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


# For multimodal content parts
class MessageContentPartText(BaseModel):
    """Represents a text content part in a multimodal message."""

    type: str = "text"
    text: str


class ImageURL(BaseModel):
    """Specifies the URL and optional detail for an image in a multimodal message."""

    # Should be a data URI (e.g., "data:image/jpeg;base64,...") or public URL
    url: str
    detail: Optional[str] = Field(None, examples=["auto", "low", "high"])


class MessageContentPartImage(BaseModel):
    """Represents an image content part in a multimodal message."""

    type: str = "image_url"
    image_url: ImageURL


# Extend with other multimodal types as needed (e.g., audio, video file, documents)
# For now, text and image are common starting points.
MessageContentPart = Union[MessageContentPartText, MessageContentPartImage]
"""Type alias for possible content parts in a multimodal message."""


class ChatMessage(BaseModel):
    """
    Represents a single message in a chat conversation, conforming to OpenAI's structure.
    Content can be a simple string or a list of multimodal content parts.
    """

    role: str
    content: Union[str, List[MessageContentPart]]
    name: Optional[str] = None
    # tool_calls: Optional[List[Any]] = None # Future extension for tool/function calling
    # tool_call_id: Optional[str] = None   # Future extension for
    # tool/function calling


class ChatCompletionRequest(BaseModel):
    """
    Represents a request for chat completions, mirroring OpenAI's API structure.
    Includes parameters for controlling the generation process (e.g., temperature, streaming).
    """

    model: str
    messages: List[ChatMessage]
    temperature: Optional[float] = Field(
        None, description="Controls randomness. Lower is more deterministic."
    )
    top_p: Optional[float] = Field(
        None,
        description="Nucleus sampling: considers tokens with top_p probability mass.",
    )
    n: Optional[int] = Field(
        None, description="Number of chat completion choices to generate."
    )
    stream: Optional[bool] = Field(
        False,
        description="If true, partial message deltas will be sent as server-sent events.",
    )
    stop: Optional[Union[str, List[str]]] = Field(
        None,
        description="Up to 4 sequences where the API will stop generating further tokens.",
    )
    max_tokens: Optional[int] = Field(
        None,
        description="The maximum number of tokens to generate in the chat completion.",
    )
    presence_penalty: Optional[float] = Field(
        None,
        description="Penalty for new tokens based on whether they appear in the text so far.",
    )
    frequency_penalty: Optional[float] = Field(
        None,
        description="Penalty for new tokens based on their existing frequency in the text so far.",
    )
    logit_bias: Optional[Dict[str, float]] = Field(
        None,
        description="Modifies the likelihood of specified tokens appearing in the completion.",
    )
    user: Optional[str] = Field(
        None,
        description="A unique identifier representing your end-user, which can help OpenAI monitor and detect abuse.",
    )
    extra_params: Optional[Dict[str, Any]] = None
    # Add other OpenAI parameters as needed, e.g., functions, tool_choice,
    # tools


class ChatCompletionChoiceMessage(BaseModel):
    """Represents the message content within a chat completion choice."""

    role: str
    content: str


class ChatCompletionChoice(BaseModel):
    """Represents a single choice in a chat completion response."""

    index: int
    message: ChatCompletionChoiceMessage
    finish_reason: str


class CompletionUsage(BaseModel):
    """Represents token usage statistics for a completion."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    """
    Represents a standard chat completion response, conforming to OpenAI's structure.
    """

    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatCompletionChoice]
    usage: Optional[CompletionUsage] = None


class CommandProcessedChatCompletionResponse(BaseModel):
    """
    Represents a simplified chat completion response for command-only requests,
    conforming to OpenAI's structure but indicating proxy processing.
    """

    id: str = "proxy_cmd_processed"
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatCompletionChoice]
    usage: CompletionUsage
