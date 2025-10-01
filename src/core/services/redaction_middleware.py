"""
Redaction middleware for the request pipeline.

This middleware handles API key redaction and command filtering to prevent
sensitive information from being sent to LLM backends.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from src.core.domain.chat import ChatRequest, MessageContentPartText
from src.core.interfaces.request_processor_interface import IRequestMiddleware
from src.security import APIKeyRedactor, ProxyCommandFilter

logger = logging.getLogger(__name__)


class RedactionMiddleware(IRequestMiddleware):
    """Middleware for redacting sensitive information from requests.

    This middleware handles API key redaction and command filtering to prevent
    sensitive information from being sent to LLM backends.
    """

    def __init__(
        self, api_keys: Iterable[str] | None = None, command_prefix: str = "!/"
    ):
        """Initialize the redaction middleware.

        Args:
            api_keys: API keys to redact
            command_prefix: Prefix for proxy commands
        """
        self._api_key_redactor = APIKeyRedactor(api_keys)
        self._command_filter = ProxyCommandFilter(command_prefix)

    async def process(
        self, request: ChatRequest, context: dict[str, Any] | None = None
    ) -> ChatRequest:
        """Process a request to redact sensitive information.

        Args:
            request: The chat request to process
            context: Additional context

        Returns:
            The processed request with sensitive information redacted
        """
        # Skip if no messages
        if not request.messages:
            return request

        # We always filter commands to prevent any command leakage to backend LLMs,
        # except for tool/function responses which contain legitimate tool output
        # (file contents, search results, etc.) that may include proxy command examples

        # Create a copy of the request to modify
        processed_request = request.model_copy(deep=True)

        # Process each message
        for message in processed_request.messages:
            if message.content:
                # Skip command filtering for tool/function responses
                # These contain legitimate tool output that may include proxy command examples
                is_tool_response = message.role in ["tool", "function"]

                # Handle string content
                if isinstance(message.content, str):
                    # Apply API key redaction
                    message.content = self._api_key_redactor.redact(message.content)
                    # Filter commands only for user/assistant/system messages
                    if not is_tool_response:
                        message.content = self._command_filter.filter_commands(
                            message.content
                        )
                # Handle list of content parts
                elif isinstance(message.content, list):
                    for part in message.content:
                        if isinstance(part, dict) and "text" in part and part["text"]:
                            # Apply API key redaction
                            part["text"] = self._api_key_redactor.redact(part["text"])
                            # Filter commands only for user/assistant/system messages
                            if not is_tool_response:
                                part["text"] = self._command_filter.filter_commands(
                                    part["text"]
                                )
                        elif isinstance(part, MessageContentPartText) and part.text:
                            # Apply API key redaction
                            part.text = self._api_key_redactor.redact(part.text)
                            # Filter commands only for user/assistant/system messages
                            if not is_tool_response:
                                part.text = self._command_filter.filter_commands(
                                    part.text
                                )

        return processed_request

    def update_api_keys(self, api_keys: Iterable[str]) -> None:
        """Update the API keys to redact.

        Args:
            api_keys: New API keys to redact
        """
        self._api_key_redactor = APIKeyRedactor(api_keys)

    def update_command_prefix(self, command_prefix: str) -> None:
        """Update the command prefix.

        Args:
            command_prefix: New command prefix
        """
        self._command_filter.set_command_prefix(command_prefix)
