from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, ConfigDict


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


class FunctionCall(BaseModel):
    """Represents a function call within a tool call."""
    
    name: str
    arguments: str


class ToolCall(BaseModel):
    """Represents a tool call in a chat completion response."""
    
    id: str
    type: str = "function"
    function: FunctionCall


class ChatCompletionRequest(BaseModel):
    """
    Represents a request for chat completions, mirroring OpenAI's API structure.
    Includes parameters for controlling the generation process (e.g., temperature, streaming).
    """

    model: str
    messages: List[ChatMessage]
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
    tools: Optional[List[ToolCall]] = None
    
    # Reasoning parameters for o1, o3, o4-mini and other reasoning models
    reasoning_effort: Optional[str] = Field(
        None, 
        description="Constrains effort on reasoning for reasoning models. Supported values: 'low', 'medium', 'high'."
    )
    reasoning: Optional[Dict[str, Any]] = Field(
        None,
        description="Unified reasoning configuration for OpenRouter. Can include 'effort', 'max_tokens', 'exclude', etc."
    )

    # Gemini-specific reasoning parameters
    thinking_budget: Optional[int] = Field(
        None,
        description="Gemini thinking budget (128-32768 tokens). Controls tokens allocated for reasoning in Gemini models."
    )
    generation_config: Optional[Dict[str, Any]] = Field(
        None,
        description="Gemini generation configuration including thinkingConfig, temperature, etc."
    )

    # Temperature configuration
    temperature: Optional[float] = Field(
        None,
        description="Controls randomness in the model's output. Range: 0.0 to 2.0 (OpenAI) or 0.0 to 1.0 (Gemini)"
    )
    
    extra_params: Optional[Dict[str, Any]] = None
    # Add other OpenAI parameters as needed, e.g., functions, tool_choice


class ChatCompletionChoiceMessage(BaseModel):
    """Represents the message content within a chat completion choice."""
    
    model_config = ConfigDict(extra='ignore')

    role: str
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None


class ChatCompletionChoice(BaseModel):
    """Represents a single choice in a chat completion response."""

    index: int
    message: ChatCompletionChoiceMessage
    finish_reason: Optional[str] = None


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


def parse_model_backend(model: str, default_backend: str = "") -> tuple[str, str]:
    """Parse model string to extract backend and actual model name.
    
    Handles multiple formats:
    - backend:model (e.g., "openrouter:gpt-4") 
    - backend/model (e.g., "openrouter/gpt-4")
    - backend:model:version (e.g., "openrouter:anthropic/claude-3-haiku:beta")
    - backend/model:version (e.g., "openrouter/anthropic/claude-3-haiku:beta")
    - model (e.g., "gpt-4" - uses default backend)

    Args:
        model: Model string in various formats
        default_backend: Default backend to use if no prefix is specified

    Returns:
        Tuple of (backend_type, model_name)
    """
    # Find the first occurrence of either ':' or '/'
    colon_pos = model.find(':')
    slash_pos = model.find('/')
    
    # Determine which separator comes first (or if only one exists)
    separator_pos = -1
    if colon_pos != -1 and slash_pos != -1:
        # Both exist, use the first one
        separator_pos = min(colon_pos, slash_pos)
    elif colon_pos != -1:
        # Only colon exists
        separator_pos = colon_pos
    elif slash_pos != -1:
        # Only slash exists
        separator_pos = slash_pos
    
    if separator_pos != -1:
        # Split at the first separator
        backend = model[:separator_pos]
        model_name = model[separator_pos + 1:]
        return backend, model_name
    else:
        # No separator found, use default backend
        return default_backend, model

# Model-specific reasoning configuration for config files
class ModelReasoningConfig(BaseModel):
    """Configuration for model-specific reasoning defaults."""
    
    # OpenAI/OpenRouter reasoning parameters
    reasoning_effort: Optional[str] = Field(
        None,
        description="Default reasoning effort for this model (low/medium/high)"
    )
    reasoning: Optional[Dict[str, Any]] = Field(
        None,
        description="Default OpenRouter unified reasoning configuration"
    )
    
    # Gemini reasoning parameters
    thinking_budget: Optional[int] = Field(
        None,
        description="Default Gemini thinking budget (128-32768 tokens)"
    )
    generation_config: Optional[Dict[str, Any]] = Field(
        None,
        description="Default Gemini generation configuration"
    )

    # Temperature configuration
    temperature: Optional[float] = Field(
        None,
        description="Default temperature for this model (0.0-2.0 for OpenAI, 0.0-1.0 for Gemini)"
    )

class ModelDefaults(BaseModel):
    """Model-specific default configurations."""
    
    reasoning: Optional[ModelReasoningConfig] = Field(
        None,
        description="Reasoning configuration defaults for this model"
    )
