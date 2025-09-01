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
)

logger = logging.getLogger(__name__)


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
