"""
API Adapters

This module contains adapter functions for converting between domain models and external API formats.
"""

from __future__ import annotations

import logging
from typing import Any

# Import domain models
from src.core.domain.chat import (
    ChatMessage,
    ChatRequest,
    FunctionCall,
    ToolCall,
    ToolDefinition,
)
from src.core.interfaces.model_bases import DomainModel, InternalDTO

logger = logging.getLogger(__name__)


def legacy_to_domain_chat_request(
    legacy_request: DomainModel | InternalDTO | dict[str, Any],
) -> ChatRequest:
    """
    Convert a legacy ChatCompletionRequest to a domain ChatRequest.

    Args:
        legacy_request: The legacy request model

    Returns:
        A domain ChatRequest model
    """
    # Convert messages (support dicts, objects with attributes, or pydantic models)
    messages: list[ChatMessage] = []
    if isinstance(legacy_request, dict):
        raw_messages = legacy_request.get("messages", [])
    else:
        raw_messages = getattr(legacy_request, "messages", [])

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
        legacy_request.get("tools")
        if isinstance(legacy_request, dict)
        else getattr(legacy_request, "tools", None)
    )
    if tools_val:
        tools = _convert_tools(tools_val)

    # Helper to extract attribute or dict item
    def _get(attr_name: str, default: Any = None) -> Any:
        if isinstance(legacy_request, dict):
            return legacy_request.get(attr_name, default)
        return getattr(legacy_request, attr_name, default)

    reasoning_effort_val = _get("reasoning_effort", None)
    extra_params = _get("extra_params", {}) or {}
    thinking_budget = _get("thinking_budget", None)
    generation_config = _get("generation_config", None)
    legacy_extra_body = _get("extra_body", None)

    # Build ChatRequest with only explicitly provided fields so pydantic's
    # `exclude_unset=True` can be relied on downstream to omit unset fields.
    rq_kwargs: dict[str, Any] = {"model": _get("model"), "messages": messages}

    def _maybe_set(name: str, val: Any) -> None:
        if val is not None:
            rq_kwargs[name] = val

    _maybe_set("temperature", _get("temperature"))
    _maybe_set("top_p", _get("top_p"))
    _maybe_set("reasoning", _get("reasoning"))
    _maybe_set("n", _get("n"))
    _maybe_set("stream", _get("stream"))
    _maybe_set("stop", _get("stop"))
    _maybe_set("max_tokens", _get("max_tokens"))
    _maybe_set("presence_penalty", _get("presence_penalty"))
    _maybe_set("frequency_penalty", _get("frequency_penalty"))
    _maybe_set("logit_bias", _get("logit_bias"))
    _maybe_set("user", _get("user"))
    if tools is not None:
        rq_kwargs["tools"] = tools
    _maybe_set("tool_choice", _get("tool_choice"))
    _maybe_set("session_id", _get("session_id", None))
    if reasoning_effort_val is not None:
        rq_kwargs["reasoning_effort"] = float(reasoning_effort_val)
    _maybe_set("thinking_budget", thinking_budget)
    _maybe_set("generation_config", generation_config)

    # Preserve explicit extra_body from callers; fall back to extra_params only
    if legacy_extra_body is not None:
        rq_kwargs["extra_body"] = legacy_extra_body
    elif extra_params:
        rq_kwargs["extra_body"] = {**extra_params}

    if tools is not None:
        rq_kwargs["tools"] = tools

    return ChatRequest(**rq_kwargs)


# Note: response conversion helpers to/from legacy dicts were removed to
# enforce domain-first handling. If code needs a legacy-compatible dict,
# use `domain_response.model_dump()` or call the adapter `domain_to_legacy_chat_request`.


def _convert_tool_calls(tool_calls: list[Any] | None) -> list[ToolCall] | None:
    """
    Convert tool calls from legacy format to domain format.

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


def _convert_tools(tools: list[Any]) -> list[dict[str, Any]] | None:
    """
    Convert tools from legacy format to domain format.

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


from fastapi import HTTPException  # Add this import

# ... (rest of the file)


def dict_to_domain_chat_request(request_dict: dict[str, Any]) -> ChatRequest:
    """
    Convert a dictionary to a domain ChatRequest.

    Args:
        request_dict: The request dictionary

    Returns:
        A domain ChatRequest model
    """
    # Handle messages specially to ensure proper conversion
    messages = request_dict.get("messages", [])

    # Add this check
    if not messages:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": "At least one message is required.",
                    "type": "invalid_request_error",
                    "param": "messages",
                    "code": "empty_messages",
                }
            },
        )
    # End of new block

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
    """
    Convert an OpenAI format request to a domain ChatRequest.

    Args:
        request_dict: The OpenAI format request dictionary

    Returns:
        A domain ChatRequest model
    """
    return dict_to_domain_chat_request(request_dict)


def anthropic_to_domain_chat_request(request_dict: dict[str, Any]) -> ChatRequest:
    """
    Convert an Anthropic format request to a domain ChatRequest.

    Args:
        request_dict: The Anthropic format request dictionary

    Returns:
        A domain ChatRequest model
    """
    # Convert Anthropic format to OpenAI format first
    # This is a placeholder - actual conversion would be more complex
    openai_format = {
        "model": request_dict.get("model", ""),
        "messages": _convert_anthropic_messages(request_dict),
        "temperature": request_dict.get("temperature"),
        "max_tokens": request_dict.get("max_tokens"),
        "stream": request_dict.get("stream", False),
    }

    return dict_to_domain_chat_request(openai_format)


def _convert_anthropic_messages(request_dict: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Convert Anthropic messages to OpenAI format messages.

    Args:
        request_dict: The Anthropic format request dictionary

    Returns:
        List of messages in OpenAI format
    """
    # This is a placeholder - actual conversion would be more complex
    # and would handle Anthropic's specific message format
    messages = []

    # Add system message if present
    if "system" in request_dict:
        messages.append({"role": "system", "content": request_dict["system"]})

    # Add user and assistant messages
    if "messages" in request_dict:
        messages.extend(request_dict["messages"])

    return messages


def gemini_to_domain_chat_request(request_dict: dict[str, Any]) -> ChatRequest:
    """
    Convert a Gemini format request to a domain ChatRequest.

    Args:
        request_dict: The Gemini format request dictionary

    Returns:
        A domain ChatRequest model
    """
    # Convert Gemini format to OpenAI format first
    # This is a placeholder - actual conversion would be more complex
    openai_format = {
        "model": request_dict.get("model", ""),
        "messages": _convert_gemini_contents(request_dict),
        "temperature": _extract_gemini_temperature(request_dict),
        "max_tokens": _extract_gemini_max_tokens(request_dict),
        "stream": request_dict.get("stream", False),
    }

    return dict_to_domain_chat_request(openai_format)


def _convert_gemini_contents(request_dict: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Convert Gemini contents to OpenAI format messages.

    Args:
        request_dict: The Gemini format request dictionary

    Returns:
        List of messages in OpenAI format
    """
    # This is a placeholder - actual conversion would be more complex
    # and would handle Gemini's specific content format
    messages = []

    # Add contents as user messages
    if "contents" in request_dict:
        for content in request_dict["contents"]:
            role = content.get("role", "user")
            parts = content.get("parts", [])

            # Extract text from parts
            text_parts = []
            for part in parts:
                if part.get("type") == "text" or "text" in part:
                    text_parts.append(part.get("text", ""))

            # Join text parts
            content_text = "".join(text_parts)

            # Add message
            messages.append({"role": role, "content": content_text})

    return messages


def _extract_gemini_temperature(request_dict: dict[str, Any]) -> float | None:
    """
    Extract temperature from Gemini request.

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
    """
    Extract max tokens from Gemini request.

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
