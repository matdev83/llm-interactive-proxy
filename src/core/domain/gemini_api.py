"""
Pydantic models for Gemini API request/response structures.

This module defines the data structures for Gemini API interactions,
replacing manual dictionary construction with type-safe Pydantic models.
"""

from typing import Any

from pydantic import BaseModel, Field


class GeminiPart(BaseModel):
    """A part within Gemini content (text, function call, etc.)."""

    text: str | None = Field(default=None, description="Text content")
    function_call: dict[str, Any] | None = Field(
        default=None, description="Function call data"
    )
    function_response: dict[str, Any] | None = Field(
        default=None, description="Function response data"
    )
    inline_data: dict[str, Any] | None = Field(
        default=None, description="Inline data (images, etc.)"
    )


class GeminiContent(BaseModel):
    """Gemini content structure containing parts and role."""

    parts: list[GeminiPart] = Field(description="List of content parts")
    role: str = Field(description="Content role (user, model, etc.)")


class GeminiFunctionDeclaration(BaseModel):
    """Gemini function declaration for tools."""

    name: str = Field(description="Function name")
    description: str | None = Field(default=None, description="Function description")
    parameters: dict[str, Any] | None = Field(
        default=None, description="Function parameters schema"
    )


class GeminiTool(BaseModel):
    """Gemini tool definition."""

    function_declarations: list[GeminiFunctionDeclaration] = Field(
        description="List of function declarations"
    )


class GeminiGenerationConfig(BaseModel):
    """Gemini generation configuration."""

    temperature: float | None = Field(
        default=None, description="Generation temperature"
    )
    max_output_tokens: int | None = Field(
        default=None, description="Maximum output tokens"
    )
    top_p: float | None = Field(default=None, description="Top-p sampling parameter")
    top_k: int | None = Field(default=None, description="Top-k sampling parameter")
    stop_sequences: list[str] | None = Field(default=None, description="Stop sequences")


class GeminiRequest(BaseModel):
    """Complete Gemini API request structure."""

    contents: list[GeminiContent] = Field(description="List of content items")
    tools: list[GeminiTool] | None = Field(default=None, description="Available tools")
    tool_config: dict[str, Any] | None = Field(
        default=None, description="Tool configuration"
    )
    safety_settings: list[dict[str, Any]] | None = Field(
        default=None, description="Safety settings"
    )
    system_instruction: GeminiContent | None = Field(
        default=None, description="System instruction"
    )
    generation_config: GeminiGenerationConfig | None = Field(
        default=None, description="Generation config"
    )
    cached_content: str | None = Field(
        default=None, description="Cached content reference"
    )


class GeminiCandidate(BaseModel):
    """Gemini response candidate."""

    content: GeminiContent | None = Field(default=None, description="Generated content")
    finish_reason: str | None = Field(default=None, description="Finish reason")
    index: int | None = Field(default=None, description="Candidate index")
    safety_ratings: list[dict[str, Any]] | None = Field(
        default=None, description="Safety ratings"
    )


class GeminiUsageMetadata(BaseModel):
    """Gemini usage metadata."""

    prompt_token_count: int | None = Field(
        default=None, description="Prompt tokens used"
    )
    candidates_token_count: int | None = Field(
        default=None, description="Candidate tokens used"
    )
    total_token_count: int | None = Field(default=None, description="Total tokens used")


class GeminiResponse(BaseModel):
    """Complete Gemini API response structure."""

    candidates: list[GeminiCandidate] | None = Field(
        default=None, description="Response candidates"
    )
    usage_metadata: GeminiUsageMetadata | None = Field(
        default=None, description="Usage information"
    )
    model_version: str | None = Field(default=None, description="Model version used")


class OpenAIToolFunction(BaseModel):
    """OpenAI tool function definition."""

    name: str = Field(description="Function name")
    description: str | None = Field(default=None, description="Function description")
    parameters: dict[str, Any] | None = Field(
        default=None, description="Function parameters"
    )


class OpenAITool(BaseModel):
    """OpenAI tool definition."""

    type: str = Field(default="function", description="Tool type")
    function: OpenAIToolFunction = Field(description="Function definition")


class OpenAIMessage(BaseModel):
    """OpenAI message structure."""

    role: str = Field(description="Message role")
    content: str | list[dict[str, Any]] | None = Field(
        default=None, description="Message content"
    )
    tool_calls: list[dict[str, Any]] | None = Field(
        default=None, description="Tool calls"
    )
    tool_call_id: str | None = Field(
        default=None, description="Tool call ID for tool responses"
    )


class OpenAIRequest(BaseModel):
    """OpenAI chat completion request structure."""

    model: str = Field(description="Model name")
    messages: list[OpenAIMessage] = Field(description="Conversation messages")
    tools: list[OpenAITool] | None = Field(default=None, description="Available tools")
    tool_choice: str | dict[str, Any] | None = Field(
        default=None, description="Tool choice preference"
    )
    temperature: float | None = Field(
        default=None, description="Generation temperature"
    )
    max_tokens: int | None = Field(default=None, description="Maximum tokens")
    top_p: float | None = Field(default=None, description="Top-p parameter")
    stop: str | list[str] | None = Field(default=None, description="Stop sequences")
    stream: bool | None = Field(default=None, description="Stream response")


def convert_openai_to_gemini_content(
    openai_messages: list[OpenAIMessage],
) -> list[GeminiContent]:
    """
    Convert OpenAI messages to Gemini content format using Pydantic models.

    Args:
        openai_messages: List of OpenAI messages

    Returns:
        List of Gemini content objects
    """
    gemini_contents = []

    for message in openai_messages:
        # Skip system messages as Gemini handles them separately
        if message.role == "system":
            continue

        # Convert role (assistant -> model)
        gemini_role = "model" if message.role == "assistant" else message.role

        parts = []

        # Handle text content
        if message.content:
            if isinstance(message.content, str):
                parts.append(GeminiPart(text=message.content))
            elif isinstance(message.content, list):
                # Handle structured content (multimodal)
                for content_item in message.content:
                    if (
                        isinstance(content_item, dict)
                        and content_item.get("type") == "text"
                    ):
                        parts.append(GeminiPart(text=content_item.get("text", "")))

        # Handle tool calls
        if message.tool_calls:
            for tool_call in message.tool_calls:
                if isinstance(tool_call, dict):
                    function_call = {
                        "name": tool_call.get("function", {}).get("name"),
                        "args": tool_call.get("function", {}).get("arguments", {}),
                    }
                    # Parse arguments if they're a JSON string
                    if isinstance(function_call["args"], str):
                        try:
                            import json

                            function_call["args"] = json.loads(function_call["args"])
                        except (json.JSONDecodeError, TypeError):  # type: ignore[name-defined]
                            pass
                        except Exception:
                            # json module might not be available in some contexts
                            pass

                    parts.append(GeminiPart(function_call=function_call))

        # Handle tool responses
        if message.tool_call_id and message.content:
            function_response = {
                "name": "function_response",  # Gemini expects this
                "response": {"result": message.content},
            }
            parts.append(GeminiPart(function_response=function_response))

        if parts:  # Only add if we have content
            gemini_contents.append(GeminiContent(parts=parts, role=gemini_role))

    return gemini_contents


def convert_gemini_to_openai_messages(
    gemini_contents: list[GeminiContent],
) -> list[OpenAIMessage]:
    """
    Convert Gemini content to OpenAI messages format using Pydantic models.

    Args:
        gemini_contents: List of Gemini content objects

    Returns:
        List of OpenAI messages
    """
    openai_messages = []

    for content in gemini_contents:
        # Convert role (model -> assistant)
        openai_role = "assistant" if content.role == "model" else content.role

        # Combine text parts
        text_parts = []
        tool_calls = []

        for part in content.parts:
            if part.text:
                text_parts.append(part.text)

            if part.function_call:
                # Convert to OpenAI tool call format
                import json

                tool_call = {
                    "id": f"call_{hash(str(part.function_call)) % 1000000}",  # Generate ID
                    "type": "function",
                    "function": {
                        "name": part.function_call.get("name"),
                        "arguments": json.dumps(part.function_call.get("args", {})),
                    },
                }
                tool_calls.append(tool_call)

        # Create message
        message_content = None
        if text_parts:
            # Handle multimodal content or simple text
            if len(text_parts) == 1:
                message_content = text_parts[0]
            else:
                message_content = "\n".join(text_parts)

        message = OpenAIMessage(
            role=openai_role,
            content=message_content,
            tool_calls=tool_calls if tool_calls else None,
        )

        openai_messages.append(message)

    return openai_messages


def convert_openai_tools_to_gemini_tools(
    openai_tools: list[OpenAITool],
) -> list[GeminiTool]:
    """
    Convert OpenAI tools to Gemini tools format using Pydantic models.

    Args:
        openai_tools: List of OpenAI tool definitions

    Returns:
        List of Gemini tool definitions
    """
    if not openai_tools:
        return []

    function_declarations = []

    for tool in openai_tools:
        if tool.type == "function" and tool.function:
            declaration = GeminiFunctionDeclaration(
                name=tool.function.name,
                description=tool.function.description,
                parameters=tool.function.parameters,
            )
            function_declarations.append(declaration)

    if function_declarations:
        return [GeminiTool(function_declarations=function_declarations)]

    return []


def convert_gemini_tools_to_openai_tools(
    gemini_tools: list[GeminiTool],
) -> list[OpenAITool]:
    """
    Convert Gemini tools to OpenAI tools format using Pydantic models.

    Args:
        gemini_tools: List of Gemini tool definitions

    Returns:
        List of OpenAI tool definitions
    """
    openai_tools = []

    for tool in gemini_tools:
        for declaration in tool.function_declarations:
            openai_tool = OpenAITool(
                type="function",
                function=OpenAIToolFunction(
                    name=declaration.name,
                    description=declaration.description,
                    parameters=declaration.parameters,
                ),
            )
            openai_tools.append(openai_tool)

    return openai_tools
