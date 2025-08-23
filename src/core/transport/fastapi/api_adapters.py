"""
FastAPI API model adapters.

This module contains adapters for converting between FastAPI API models
and domain models.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.common.exceptions import InvalidRequestError
from src.core.domain.chat import (
    ChatMessage,
    ChatRequest,
    FunctionCall,
    ToolCall,
    ToolDefinition,
)

logger = logging.getLogger(__name__)


def _convert_tool_calls(tool_calls: list[Any] | None) -> list[ToolCall] | None:
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


def _convert_tools(tools: list[Any]) -> list[dict[str, Any]] | None:
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
