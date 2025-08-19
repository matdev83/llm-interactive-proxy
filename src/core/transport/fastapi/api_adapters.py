"""
FastAPI API model adapters.

This module contains adapters for converting between FastAPI API models
and domain models.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Union, cast

from src.core.common.exceptions import InvalidRequestError
from src.core.domain.chat import (
    ChatMessage,
    ChatRequest,
    FunctionCall,
    ToolCall,
    ToolDefinition,
)

logger = logging.getLogger(__name__)


def legacy_to_domain_chat_request(request_data: Any) -> ChatRequest:
    """Convert a legacy request data object to a domain ChatRequest.
    
    Args:
        request_data: The legacy request data
        
    Returns:
        A domain ChatRequest object
    """
    # If it's already a ChatRequest, just return it
    if isinstance(request_data, ChatRequest):
        return request_data
    
    # Convert messages (support dicts, objects with attributes, or pydantic models)
    messages: list[ChatMessage] = []
    if isinstance(request_data, dict):
        raw_messages = request_data.get("messages", [])
    else:
        raw_messages = getattr(request_data, "messages", [])

    for msg in raw_messages:
        if isinstance(msg, dict):
            role = msg.get("role", "user")
            content = msg.get("content")
            name = msg.get("name")
            tool_calls_val = msg.get("tool_calls")
            tool_call_id = msg.get("tool_call_id")
        else:
            role = getattr(msg, "role", "user")
            content = getattr(msg, "content", None)
            name = getattr(msg, "name", None)
            tool_calls_val = getattr(msg, "tool_calls", None)
            tool_call_id = getattr(msg, "tool_call_id", None)

        domain_msg = ChatMessage(
            role=role,
            content=content,
            name=name,
            tool_calls=_convert_tool_calls(tool_calls_val),
            tool_call_id=tool_call_id,
        )
        messages.append(domain_msg)

    # Convert tools
    tools = None
    tools_val = (
        request_data.get("tools")
        if isinstance(request_data, dict)
        else getattr(request_data, "tools", None)
    )
    if tools_val:
        tools = _convert_tools(tools_val)

    # Helper to extract attribute or dict item
    def _get(attr_name: str, default: Any = None) -> Any:
        if isinstance(request_data, dict):
            return request_data.get(attr_name, default)
        return getattr(request_data, attr_name, default)

    reasoning_effort_val = _get("reasoning_effort", None)
    extra_params = _get("extra_params", {}) or {}
    thinking_budget = _get("thinking_budget", None)
    generation_config = _get("generation_config", None)

    return ChatRequest(
        model=_get("model"),
        messages=messages,
        temperature=_get("temperature"),
        top_p=_get("top_p"),
        n=_get("n"),
        stream=_get("stream"),
        stop=_get("stop"),
        max_tokens=_get("max_tokens"),
        presence_penalty=_get("presence_penalty"),
        frequency_penalty=_get("frequency_penalty"),
        logit_bias=_get("logit_bias"),
        user=_get("user"),
        tools=tools,
        tool_choice=_get("tool_choice"),
        session_id=_get("session_id", None),
        reasoning_effort=(
            None if reasoning_effort_val is None else float(reasoning_effort_val)
        ),
        extra_body={
            **(extra_params or {}),
            **(
                {"thinking_budget": thinking_budget}
                if thinking_budget is not None
                else {}
            ),
            **(
                {"generation_config": generation_config}
                if generation_config is not None
                else {}
            ),
        },
    )


def domain_to_legacy_chat_request(domain_request: ChatRequest) -> dict[str, Any]:
    """Convert a domain ChatRequest to a legacy-compatible dict.

    This returns a plain dict compatible with the legacy ChatCompletionRequest
    shape so callers that still expect legacy structures can continue to
    operate without importing `src.models`.
    """
    # Convert to dict first to handle all fields
    request_dict = domain_request.to_legacy_format()

    # Handle extra_body separately
    extra_params = domain_request.extra_body

    # Remove extra_body from request_dict if it exists
    if "extra_body" in request_dict:
        del request_dict["extra_body"]

    # Attach extra_params under legacy name
    if extra_params:
        request_dict["extra_params"] = extra_params

    return request_dict


def _convert_tool_calls(
    tool_calls: list[Any] | None,
) -> list[ToolCall] | None:
    """Convert tool calls from legacy format to domain format.

    Args:
        tool_calls: List of tool calls in legacy format

    Returns:
        List of tool calls in domain format
    """
    if not tool_calls:
        return None

    domain_tool_calls = []
    for tc in tool_calls:
        # Check if it's already a domain ToolCall
        if isinstance(tc, ToolCall):
            domain_tool_calls.append(tc)
            continue

        # Convert from dict or legacy model
        tc_dict = tc if isinstance(tc, dict) else tc.model_dump()

        # Extract function call
        function_dict = tc_dict.get("function", {})
        function_call = FunctionCall(
            name=function_dict.get("name", ""),
            arguments=function_dict.get("arguments", ""),
        )

        # Create domain tool call
        domain_tool_call = ToolCall(
            id=tc_dict.get("id", ""),
            type=tc_dict.get("type", "function"),
            function=function_call,
        )

        domain_tool_calls.append(domain_tool_call)

    return domain_tool_calls


def _convert_tools(
    tools: list[Any],
) -> list[dict[str, Any]] | None:
    """Convert tools from legacy format to domain format.

    Args:
        tools: List of tools in legacy format

    Returns:
        List of tools in domain format
    """
    if not tools:
        return None

    domain_tools = []
    for tool in tools:
        # Check if it's already a domain ToolDefinition
        if isinstance(tool, ToolDefinition):
            domain_tools.append(tool.model_dump())
            continue

        # Convert from dict or legacy model
        tool_dict = tool if isinstance(tool, dict) else tool.model_dump()
        domain_tools.append(tool_dict)

    return domain_tools


def dict_to_domain_chat_request(request_dict: dict[str, Any]) -> ChatRequest:
    """Convert a dictionary to a domain ChatRequest.

    Args:
        request_dict: The request dictionary

    Returns:
        A domain ChatRequest model
        
    Raises:
        InvalidRequestError: If the request is invalid (e.g., no messages)
    """
    # Handle messages specially to ensure proper conversion
    messages = request_dict.get("messages", [])

    # Add this check
    if not messages:
        raise InvalidRequestError(
            message="At least one message is required.",
            param="messages",
            code="empty_messages",
        )

    domain_messages = []

    for message in messages:
        if isinstance(message, dict):
            domain_messages.append(ChatMessage(**message))
        elif isinstance(message, ChatMessage):
            domain_messages.append(message)
        else:
            # Try to convert to dict or legacy model
            if hasattr(message, "model_dump"):
                msg_dict = message.model_dump()
            elif hasattr(message, "dict"):
                msg_dict = message.dict()
            else:
                msg_dict = message
            domain_messages.append(ChatMessage(**msg_dict))

    # Create a copy of the request dict and update messages
    request_copy = dict(request_dict)
    request_copy["messages"] = domain_messages

    # Create domain request
    return ChatRequest(**request_copy)


def openai_to_domain_chat_request(request_dict: dict[str, Any]) -> ChatRequest:
    """Convert an OpenAI format request to a domain ChatRequest.

    Args:
        request_dict: The OpenAI format request dictionary

    Returns:
        A domain ChatRequest model
    """
    return dict_to_domain_chat_request(request_dict)


def anthropic_to_domain_chat_request(request_dict: dict[str, Any]) -> ChatRequest:
    """Convert an Anthropic format request to a domain ChatRequest.

    Args:
        request_dict: The Anthropic format request dictionary

    Returns:
        A domain ChatRequest model
    """
    # Convert Anthropic format to OpenAI format first
    openai_format = {
        "model": request_dict.get("model", ""),
        "messages": _convert_anthropic_messages(request_dict),
        "temperature": request_dict.get("temperature"),
        "max_tokens": request_dict.get("max_tokens"),
        "stream": request_dict.get("stream", False),
    }

    return dict_to_domain_chat_request(openai_format)


def _convert_anthropic_messages(request_dict: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert Anthropic messages to OpenAI format messages.

    Args:
        request_dict: The Anthropic format request dictionary

    Returns:
        List of messages in OpenAI format
    """
    messages = []

    # Add system message if present
    if "system" in request_dict:
        messages.append({"role": "system", "content": request_dict["system"]})

    # Add user and assistant messages
    if "messages" in request_dict:
        messages.extend(request_dict["messages"])

    return messages


def gemini_to_domain_chat_request(request_dict: dict[str, Any]) -> ChatRequest:
    """Convert a Gemini format request to a domain ChatRequest.

    Args:
        request_dict: The Gemini format request dictionary

    Returns:
        A domain ChatRequest model
    """
    # Convert Gemini format to OpenAI format first
    openai_format = {
        "model": request_dict.get("model", ""),
        "messages": _convert_gemini_contents(request_dict),
        "temperature": _extract_gemini_temperature(request_dict),
        "max_tokens": _extract_gemini_max_tokens(request_dict),
        "stream": request_dict.get("stream", False),
    }

    return dict_to_domain_chat_request(openai_format)


def _convert_gemini_contents(request_dict: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert Gemini contents to OpenAI format messages.

    Args:
        request_dict: The Gemini format request dictionary

    Returns:
        List of messages in OpenAI format
    """
    messages = []

    # Add contents as user messages
    if "contents" in request_dict:
        for content in request_dict["contents"]:
            role = content.get("role", "user")
            parts = content.get("parts", [])

            # Extract text from parts
            text_parts = []
            for part in parts:
                if part.get("type") == "text":
                    text_parts.append(part.get("text", ""))

            # Join text parts
            content_text = "".join(text_parts)

            # Add message
            messages.append({"role": role, "content": content_text})

    return messages


def _extract_gemini_temperature(request_dict: dict[str, Any]) -> float | None:
    """Extract temperature from Gemini request.

    Args:
        request_dict: The Gemini format request dictionary

    Returns:
        Temperature value or None
    """
    # Check in generationConfig
    if "generationConfig" in request_dict:
        temp = request_dict["generationConfig"].get("temperature")
        return float(temp) if temp is not None else None

    return None


def _extract_gemini_max_tokens(request_dict: dict[str, Any]) -> int | None:
    """Extract max tokens from Gemini request.

    Args:
        request_dict: The Gemini format request dictionary

    Returns:
        Max tokens value or None
    """
    # Check in generationConfig
    if "generationConfig" in request_dict:
        max_tokens = request_dict["generationConfig"].get("maxOutputTokens")
        return int(max_tokens) if max_tokens is not None else None

    return None