"""
Redaction middleware for the request pipeline.

This middleware handles API key redaction to prevent sensitive information
from being sent to LLM backends.

Optimization: Uses session-level caching to avoid reprocessing historical
messages that have already been redacted in previous requests.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from pydantic.types import JsonValue

from src.core.domain.chat import ChatMessage, ChatRequest, MessageContentPartText
from src.core.interfaces.request_processor_interface import IRequestMiddleware
from src.core.services.redaction_cache import (
    get_global_redaction_cache,
)
from src.security import APIKeyRedactor

logger = logging.getLogger(__name__)


class RedactionMiddleware(IRequestMiddleware):
    """Middleware for redacting sensitive information from requests.

    This middleware handles API key redaction to prevent sensitive information
    from being sent to LLM backends.
    """

    def __init__(
        self,
        api_keys: Iterable[str] | None = None,
    ):
        """Initialize the redaction middleware.

        Args:
            api_keys: API keys to redact
        """
        self._api_key_redactor = APIKeyRedactor(api_keys)

    async def process(
        self, request: ChatRequest, context: dict[str, JsonValue] | None = None
    ) -> ChatRequest:
        """Process a request to redact sensitive information.

        Args:
            request: The chat request to process
            context: Additional context (should include 'session_id' for caching)

        Returns:
            The processed request with sensitive information redacted
        """
        total_messages = len(request.messages) if request.messages else 0
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"RedactionMiddleware.process called with {total_messages} messages"
            )
        # Skip if no messages
        if not request.messages:
            return request

        # Get session_id for caching optimization
        session_id: str | None = None
        if context:
            session_id_value = context.get("session_id")
            session_id = session_id_value if isinstance(session_id_value, str) else None

        # Get the redaction cache for session-level optimization
        cache = get_global_redaction_cache() if session_id else None

        # Create a copy of the request to modify
        processed_request = request.model_copy(deep=True)

        # Optimization: Get indices of messages that need processing
        # (skip already-processed messages from previous requests in this session)
        if cache and session_id:
            unprocessed_indices = set(
                cache.get_unprocessed_indices(session_id, processed_request.messages)
            )
            skipped_count = len(processed_request.messages) - len(unprocessed_indices)
            if skipped_count > 0 and logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Redaction cache hit: skipping {skipped_count} already-processed "
                    f"messages, processing {len(unprocessed_indices)} new messages"
                )
        else:
            # No caching - process all messages
            unprocessed_indices = set(range(len(processed_request.messages)))

        # Track messages we process for cache update
        newly_processed_messages: list[ChatMessage] = []

        # Process only unprocessed messages
        for idx, message in enumerate(processed_request.messages):
            # Skip already-processed messages
            if idx not in unprocessed_indices:
                continue

            if message.content:
                # Handle string content
                if isinstance(message.content, str):
                    # Apply API key redaction
                    message.content = self._api_key_redactor.redact(message.content)
                # Handle list of content parts
                elif isinstance(message.content, list):
                    for part in message.content:
                        if isinstance(part, dict) and "text" in part and part["text"]:
                            # Apply API key redaction
                            part["text"] = self._api_key_redactor.redact(part["text"])
                        elif isinstance(part, MessageContentPartText) and part.text:
                            # Apply API key redaction
                            part.text = self._api_key_redactor.redact(part.text)

            newly_processed_messages.append(message)

        # Update cache with newly processed messages
        if cache and session_id and newly_processed_messages:
            cache.mark_batch_processed(session_id, newly_processed_messages)
            if logger.isEnabledFor(logging.DEBUG):
                stats = cache.get_stats(session_id)
                logger.debug(
                    f"Redaction cache updated for session {session_id}: "
                    f"{stats.cached_hashes} hashes cached, "
                    f"{stats.total_processed} total processed"
                )

        return processed_request

    def update_api_keys(self, api_keys: Iterable[str]) -> None:
        """Update the API keys to redact.

        Args:
            api_keys: New API keys to redact
        """
        self._api_key_redactor = APIKeyRedactor(api_keys)
