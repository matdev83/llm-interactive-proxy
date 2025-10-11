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
        self._strict_command_detection = strict_command_detection

    @staticmethod
    def _extract_text(part: Any) -> str | None:
        """Extract the text payload from a message part if available."""

        if isinstance(part, MessageContentPartText):
            return part.text
        if isinstance(part, dict):
            text = part.get("text")
            if isinstance(text, str):
                return text
        return None

    @staticmethod
    def _assign_text(part: Any, value: str) -> None:
        """Assign text back to a message part, preserving its structure."""

        if isinstance(part, MessageContentPartText):
            part.text = value
        elif isinstance(part, dict):
            part["text"] = value

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

        # Since request and messages may be frozen Pydantic models, we need to create
        # new message objects with modified content
        from src.core.domain.chat import ChatMessage

        new_messages = []
        num_messages = len(request.messages)

        for i, message in enumerate(request.messages):
            if not message.content:
                new_messages.append(message)
                continue

            is_last_message = i == num_messages - 1
            is_tool_response = message.role in ["tool", "function"]

            new_content = message.content

            # Redact API keys from all messages
            if isinstance(message.content, str):
                new_content = self._api_key_redactor.redact(message.content)
            elif isinstance(message.content, list | tuple):
                # For list content, we need to process each part
                new_content_list: list[Any] = []
                for part in message.content:
                    part_text = self._extract_text(part)
                    if part_text:
                        redacted_text = self._api_key_redactor.redact(part_text)
                        if isinstance(part, MessageContentPartText):
                            new_content_list.append(
                                MessageContentPartText(text=redacted_text)
                            )
                        else:
                            # For other types (like MessageContentPartImage), keep as is
                            new_content_list.append(part)
                    else:
                        new_content_list.append(part)
                new_content = new_content_list

            # Only filter commands on the last message, and only if it's not a tool response
            if is_last_message and not is_tool_response:
                filter_fn = (
                    self._command_filter.filter_commands_with_strict_mode
                    if self._strict_command_detection
                    else self._command_filter.filter_commands
                )

                if isinstance(new_content, str):
                    new_content = filter_fn(new_content)
                elif isinstance(new_content, list):
                    # Only filter the last text part, need to modify the list
                    for index in reversed(range(len(new_content))):
                        part = new_content[index]
                        part_text = self._extract_text(part)
                        if not part_text or not part_text.strip():
                            continue

                        filtered_text = filter_fn(part_text)
                        if isinstance(part, MessageContentPartText):
                            new_content[index] = MessageContentPartText(
                                text=filtered_text
                            )
                        # Only handle MessageContentPartText and MessageContentPartImage, no dicts
                        break

            # Create new message with potentially modified content
            if new_content != message.content:
                new_message = ChatMessage(
                    role=message.role,
                    content=new_content,
                    name=message.name,
                    tool_call_id=message.tool_call_id,
                    tool_calls=message.tool_calls,
                )
                new_messages.append(new_message)
            else:
                new_messages.append(message)

        # Create new request with modified messages
        return request.model_copy(update={"messages": new_messages})

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
