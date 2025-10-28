"""
Redaction middleware for the request pipeline.

This middleware handles API key redaction and command filtering to prevent
sensitive information from being sent to LLM backends.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from src.core.common.env_utils import get_env_flag
from src.core.domain.chat import ChatMessage, ChatRequest, MessageContentPartText
from src.core.interfaces.request_processor_interface import IRequestMiddleware
from src.security import APIKeyRedactor, ProxyCommandFilter

logger = logging.getLogger(__name__)


class RedactionMiddleware(IRequestMiddleware):
    """Middleware for redacting sensitive information from requests.

    This middleware handles API key redaction and command filtering to prevent
    sensitive information from being sent to LLM backends.
    """

    _MAX_PROXY_TOOL_OUTPUTS: int = 2

    def __init__(
        self,
        api_keys: Iterable[str] | None = None,
        command_prefix: str = "/",
        strict_command_detection: bool = False,
    ):
        """Initialize the redaction middleware.

        Args:
            api_keys: API keys to redact
            command_prefix: Prefix for proxy commands
            strict_command_detection: If True, only filter commands on last non-blank line
        """
        self._api_key_redactor = APIKeyRedactor(api_keys)
        self._command_filter = ProxyCommandFilter(command_prefix)
        if not strict_command_detection:
            strict_command_detection = get_env_flag("STRICT_COMMAND_DETECTION", False)
        self._strict_command_detection = strict_command_detection

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
        logger.debug(
            f"RedactionMiddleware.process called with {len(request.messages if request.messages else [])} messages"
        )
        # Skip if no messages
        if not request.messages:
            return request

        # We always filter commands to prevent any command leakage to backend LLMs,
        # except for tool/function responses which contain legitimate tool output
        # (file contents, search results, etc.) that may include proxy command examples

        # Create a copy of the request to modify
        processed_request = request.model_copy(deep=True)

        # Remove proxy command response pairs before redaction to avoid forwarding
        # large command outputs back to the backend LLM. These responses are marked
        # with metadata {"is_proxy_response": True} by the response manager.
        messages = list(processed_request.messages)
        if messages:
            indices_to_remove: set[int] = set()
            for idx, message in enumerate(messages):
                if self._is_proxy_response_message(message):
                    indices_to_remove.add(idx)
                    prev_idx = idx - 1
                    if prev_idx >= 0 and self._is_corresponding_command(
                        messages[prev_idx]
                    ):
                        indices_to_remove.add(prev_idx)

            if indices_to_remove:
                processed_request = processed_request.model_copy(
                    update={
                        "messages": [
                            msg
                            for i, msg in enumerate(messages)
                            if i not in indices_to_remove
                        ]
                    }
                )
                messages = list(processed_request.messages)

        if messages:
            proxy_tool_indices = [
                idx
                for idx, message in enumerate(messages)
                if self._is_proxy_tool_output_message(message)
            ]

            if len(proxy_tool_indices) > self._MAX_PROXY_TOOL_OUTPUTS:
                keep = set(proxy_tool_indices[-self._MAX_PROXY_TOOL_OUTPUTS :])
                processed_request = processed_request.model_copy(
                    update={
                        "messages": [
                            msg
                            for i, msg in enumerate(messages)
                            if i in keep or i not in proxy_tool_indices
                        ]
                    }
                )
                messages = list(processed_request.messages)

        # Process each remaining message
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
                        if self._strict_command_detection:
                            message.content = (
                                self._command_filter.filter_commands_with_strict_mode(
                                    message.content
                                )
                            )
                        else:
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
                                if self._strict_command_detection:
                                    part["text"] = (
                                        self._command_filter.filter_commands_with_strict_mode(
                                            part["text"]
                                        )
                                    )
                                else:
                                    part["text"] = self._command_filter.filter_commands(
                                        part["text"]
                                    )
                        elif isinstance(part, MessageContentPartText) and part.text:
                            # Apply API key redaction
                            part.text = self._api_key_redactor.redact(part.text)
                            # Filter commands only for user/assistant/system messages
                            if not is_tool_response:
                                if self._strict_command_detection:
                                    part.text = self._command_filter.filter_commands_with_strict_mode(
                                        part.text
                                    )
                                else:
                                    part.text = self._command_filter.filter_commands(
                                        part.text
                                    )

        return processed_request

    @staticmethod
    def _is_proxy_response_message(message: ChatMessage) -> bool:
        """Check if message is a proxy response generated by the proxy itself."""
        metadata = getattr(message, "metadata", None)
        if not isinstance(metadata, dict):
            return False
        return bool(metadata.get("is_proxy_response"))

    @staticmethod
    def _is_proxy_tool_output_message(message: ChatMessage) -> bool:
        metadata = getattr(message, "metadata", None)
        if not isinstance(metadata, dict):
            return False
        return bool(metadata.get("is_proxy_tool_output"))

    def _is_corresponding_command(self, message: ChatMessage) -> bool:
        """Check if message looks like a proxy command entry."""
        if message.role != "user":
            return False
        content = getattr(message, "content", None)
        if not isinstance(content, str):
            return False
        stripped = content.strip()
        command_prefix = getattr(self._command_filter, "command_prefix", "!/")
        if not isinstance(command_prefix, str) or not command_prefix:
            command_prefix = "!/"
        return bool(stripped) and stripped.startswith(command_prefix)

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

    def update_strict_command_detection(self, strict_mode: bool) -> None:
        """Update the strict command detection mode.

        Args:
            strict_mode: Whether to enable strict command detection
        """
        self._strict_command_detection = strict_mode
