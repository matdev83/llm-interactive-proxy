"""
Redaction middleware for the request pipeline.

This middleware handles API key redaction and command filtering to prevent
sensitive information from being sent to LLM backends.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from typing import Any

from src.core.domain.chat import ChatRequest
from src.core.interfaces.request_processor import IRequestMiddleware

logger = logging.getLogger(__name__)


class APIKeyRedactor:
    """Redact known API keys from user provided prompts."""

    def __init__(self, api_keys: Iterable[str] | None = None) -> None:
        """Initialize the API key redactor.

        Args:
            api_keys: Iterable of API keys to redact
        """
        # filter out falsy values
        self.api_keys = [k for k in (api_keys or []) if k]
        # Pre-compile regex patterns for better performance
        self._key_patterns = {}
        for key in self.api_keys:
            if key:
                # Escape special regex characters and compile pattern
                self._key_patterns[key] = re.compile(re.escape(key))

    def _redact_cached(self, text: str) -> str:
        """Cached version of redact for frequently processed content."""
        # Simple manual caching to avoid memory leaks with lru_cache on methods
        if not hasattr(self, "_redact_cache"):
            self._redact_cache: dict[str, str] = {}
        if text in self._redact_cache:
            return self._redact_cache[text]
        result = self._redact_internal(text)
        if len(self._redact_cache) < 1024:  # Limit cache size
            self._redact_cache[text] = result
        return result

    def redact(self, text: str) -> str:
        """Replace any occurrences of known API keys in *text*.

        Args:
            text: The text to redact

        Returns:
            The redacted text
        """
        if not text:
            return text

        # For short texts, use cached version for better performance
        if len(text) < 1000:
            return self._redact_cached(text)
        else:
            return self._redact_internal(text)

    def _redact_internal(self, text: str) -> str:
        """Internal redact implementation."""
        redacted_text = text

        # Quick containment check before expensive regex operations
        for key in self.api_keys:
            if key and key in redacted_text:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "API key detected in prompt. Redacting before forwarding."
                    )
                # Use pre-compiled regex for replacement
                pattern = self._key_patterns[key]
                redacted_text = pattern.sub(
                    "(API_KEY_HAS_BEEN_REDACTED)", redacted_text
                )

        return redacted_text


class ProxyCommandFilter:
    """Emergency filter to detect and remove proxy commands from text being sent to remote LLMs."""

    def __init__(self, command_prefix: str = "!/") -> None:
        """Initialize the proxy command filter.

        Args:
            command_prefix: The prefix used for proxy commands
        """
        self.command_prefix = command_prefix
        self._update_pattern()

    def _update_pattern(self) -> None:
        """Update the regex pattern when command prefix changes."""
        prefix_escaped = re.escape(self.command_prefix)
        # Pattern to match any proxy command: prefix followed by command name and optional arguments
        self.command_pattern = re.compile(
            rf"{prefix_escaped}(?:(?:hello|help)(?!\()\b|[\w-]+(?:\([^)]*\))?)",
            re.IGNORECASE,
        )

    def set_command_prefix(self, new_prefix: str) -> None:
        """Update the command prefix and regenerate the pattern.

        Args:
            new_prefix: The new command prefix
        """
        self.command_prefix = new_prefix
        self._update_pattern()

    def filter_commands(self, text: str) -> str:
        """Remove any proxy commands from text and issue warnings.

        This is an emergency filter to prevent command leaks to remote LLMs.

        Args:
            text: The text to filter

        Returns:
            The filtered text
        """
        if not text or not text.strip():
            return text

        # Find all command matches
        matches = list(self.command_pattern.finditer(text))

        if matches:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "EMERGENCY FILTER TRIGGERED: %d proxy command(s) detected in text being sent to remote LLM. "
                    "This indicates a potential command leak or mishandling. Commands will be removed.",
                    len(matches),
                )

            # Remove commands from text
            filtered_text = text
            # Process matches in reverse to avoid index shifting
            for match in reversed(matches):
                start, end = match.span()
                filtered_text = filtered_text[:start] + filtered_text[end:]

            return filtered_text
        return text


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

        # Create a copy of the request to modify
        processed_request = request.model_copy(deep=True)

        # Process each message
        for message in processed_request.messages:
            if message.content:
                # Handle string content
                if isinstance(message.content, str):
                    # Apply API key redaction
                    message.content = self._api_key_redactor.redact(message.content)
                    # Apply command filtering
                    message.content = self._command_filter.filter_commands(
                        message.content
                    )
                # Handle list of content parts
                elif isinstance(message.content, list):
                    for part in message.content:
                        if hasattr(part, "text") and part.text:
                            # Apply API key redaction
                            part.text = self._api_key_redactor.redact(part.text)
                            # Apply command filtering
                            part.text = self._command_filter.filter_commands(part.text)

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
