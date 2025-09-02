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
    ToolCall,
)

logger = logging.getLogger(__name__)


from src.core.common.exceptions import InvalidRequestError

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
        # Domain-centric: raise project InvalidRequestError; transports map to HTTP
        raise InvalidRequestError(
            message="At least one message is required.",
            param="messages",
            code="empty_messages",
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
    This implementation performs a more robust conversion of message formats.
    Args:
        request_dict: The Anthropic format request dictionary
    Returns:
        A domain ChatRequest model
    """
    # More robust conversion from Anthropic to a neutral format
    domain_messages = _convert_anthropic_messages(request_dict)

    # Map other parameters
    domain_request_dict = {
        "model": request_dict.get("model", ""),
        "messages": domain_messages,
        "temperature": request_dict.get("temperature"),
        "max_tokens": request_dict.get("max_tokens"),
        "stream": request_dict.get("stream", False),
        # Assuming other Anthropic-specific params are in extra_body
        "extra_body": {
            "top_k": request_dict.get("top_k"),
            "top_p": request_dict.get("top_p"),
        },
    }

    return dict_to_domain_chat_request(domain_request_dict)


def _convert_anthropic_messages(request_dict: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Convert Anthropic messages to a format closer to the domain model.
    Args:
        request_dict: The Anthropic format request dictionary
    Returns:
        List of messages in a neutral format.
    """
    messages = []
    if request_dict.get("system"):
        messages.append({"role": "system", "content": request_dict["system"]})

    if "messages" in request_dict:
        for msg in request_dict["messages"]:
            role = msg.get("role")
            content = msg.get("content")
            # A more robust implementation would handle multimodal content (list of blocks)
            # For now, we assume content is a string.
            if role and content:
                messages.append({"role": role, "content": content})

    return messages


def gemini_to_domain_chat_request(request_dict: dict[str, Any]) -> ChatRequest:
    """
    Convert a Gemini format request to a domain ChatRequest.
    This implementation performs a more robust conversion of message formats.
    Args:
        request_dict: The Gemini format request dictionary
    Returns:
        A domain ChatRequest model
    """
    domain_messages = _convert_gemini_contents(request_dict)

    domain_request_dict = {
        "model": request_dict.get("model", ""),
        "messages": domain_messages,
        "temperature": _extract_gemini_temperature(request_dict),
        "max_tokens": _extract_gemini_max_tokens(request_dict),
        "stream": "stream" in request_dict.get("endpoint", ""),  # Infer from endpoint
        "extra_body": {
            "generationConfig": request_dict.get("generationConfig"),
            "safetySettings": request_dict.get("safetySettings"),
            "tools": request_dict.get("tools"),
        },
    }

    return dict_to_domain_chat_request(domain_request_dict)


def _convert_gemini_contents(request_dict: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Convert Gemini contents to a format closer to the domain model.
    Args:
        request_dict: The Gemini format request dictionary
    Returns:
        List of messages in a neutral format.
    """
    messages = []
    if "contents" in request_dict:
        for content_item in request_dict["contents"]:
            role = content_item.get("role", "user")
            # Gemini roles are 'user' and 'model'. Map 'model' to 'assistant'.
            if role == "model":
                role = "assistant"

            parts = content_item.get("parts", [])
            # For now, we'll just concatenate text parts.
            # A full implementation would handle multimodal parts (e.g. inline_data).
            content_text = "".join(
                part.get("text", "") for part in parts if "text" in part
            ).strip()

            if content_text:
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


def _convert_tool_calls(
    tool_calls: list[dict[str, Any]] | None,
) -> list[ToolCall] | None:
    """
    Convert tool calls to domain ToolCall objects.

    Args:
        tool_calls: List of tool calls in various formats

    Returns:
        List of domain ToolCall objects or None
    """
    if tool_calls is None or not tool_calls:
        return None

    converted_tool_calls = []
    for tool_call in tool_calls:
        if isinstance(tool_call, ToolCall):
            # Already a domain ToolCall object
            converted_tool_calls.append(tool_call)
        elif isinstance(tool_call, dict):
            # Dict format - convert directly
            converted_tool_calls.append(ToolCall(**tool_call))
        else:
            # Legacy model object - try to convert via model_dump
            if hasattr(tool_call, "model_dump"):
                tool_call_dict = tool_call.model_dump()
                converted_tool_calls.append(ToolCall(**tool_call_dict))
            else:
                # Fallback - try to convert directly
                converted_tool_calls.append(ToolCall(**tool_call))

    return converted_tool_calls


def _convert_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """
    Convert tools to domain tool format.

    Args:
        tools: List of tools in various formats

    Returns:
        List of domain tool definitions or None
    """
    if tools is None or not tools:
        return None

    converted_tools = []
    for tool in tools:
        if isinstance(tool, dict):
            # Already in dict format
            converted_tools.append(tool)
        else:
            # Legacy model object - try to convert via model_dump
            if hasattr(tool, "model_dump"):
                tool_dict = tool.model_dump()
                converted_tools.append(tool_dict)
            else:
                # Fallback - try to convert directly
                converted_tools.append(dict(tool))

    return converted_tools
