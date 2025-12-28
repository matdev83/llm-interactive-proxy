"""
Backend request preparation service implementation.

This module provides the implementation of the backend request preparation interface,
extracting request preparation logic from BackendRequestManager for modularity.

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 5.4, 8.1, 9.1
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from pydantic import ValidationError

from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.configuration.compaction_config import (
    CompactionConfig,
    TokenBudgetConfig,
)
from src.core.domain.processed_result import ProcessedResult
from src.core.interfaces.backend_request_manager_components import (
    IBackendRequestPreparation,
)
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.history_compaction_interface import (
    IHistoryCompactionService,
)

logger = logging.getLogger(__name__)


class BackendRequestPreparationService(IBackendRequestPreparation):
    """Service for preparing backend requests from command results and compaction."""

    def __init__(
        self,
        history_compaction_service: IHistoryCompactionService | None = None,
        config: IConfig | None = None,
    ) -> None:
        """Initialize the request preparation service.

        Args:
            history_compaction_service: Optional service for compacting history
            config: Optional application configuration
        """
        self._history_compaction_service = history_compaction_service
        self._config = config

    async def prepare(
        self,
        request: ChatRequest,
        command_result: ProcessedResult,
    ) -> ChatRequest | None:
        """Return a new request with normalized messages or None to skip backend.

        Args:
            request: The original backend request
            command_result: Result of command processing

        Returns:
            A new request with normalized messages, or None to skip backend execution

        Preconditions:
            - request.messages and command_result are non-null

        Postconditions:
            - Returned request uses new message list when modified
            - Original request instance is not mutated
        """
        final_request = request

        # Process command results if commands were executed
        if command_result.command_executed:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Command executed; modified_messages_count=%s, command_results_count=%s",
                    len(command_result.modified_messages or []),
                    len(command_result.command_results or []),
                )

            final_messages: list[ChatMessage] = list(request.messages)
            messages_were_modified = False

            # Process modified_messages: if they exist and have content, they replace original messages
            if command_result.modified_messages:
                if any(
                    self._message_has_content(m)
                    for m in command_result.modified_messages
                ):
                    normalized_messages: list[ChatMessage] = []
                    for m in command_result.modified_messages:
                        if isinstance(m, ChatMessage):
                            normalized_messages.append(m)
                        elif isinstance(m, dict):
                            normalized_messages.append(ChatMessage(**m))
                        else:
                            normalized_messages.append(
                                ChatMessage(
                                    role=getattr(m, "role", "user"),
                                    content=getattr(m, "content", ""),
                                )
                            )
                    final_messages = normalized_messages
                    messages_were_modified = True
                else:
                    # All modified messages are empty, skip backend call
                    return None

            # Process command_results: append tool outputs to the message list
            if command_result.command_results:
                extra_messages = []
                for result in command_result.command_results:
                    extracted = self._extract_messages_from_command_result(result)
                    if extracted:
                        extra_messages.extend(extracted)

                if extra_messages:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Appending %s command result messages to backend request",
                            len(extra_messages),
                        )
                    final_messages.extend(extra_messages)
                    messages_were_modified = True

            # If messages were changed, create a new request object
            if messages_were_modified:
                final_request = request.model_copy(update={"messages": final_messages})

        # Apply history compaction to reduce stale tool outputs
        # This is done after command processing but before connector translation
        # Use history compaction if available and we have a token count
        if self._history_compaction_service is not None:
            # Fast approximate token estimate using character count / 4
            # This is O(n) and avoids expensive tokenization for threshold checking
            # Actual tokenization happens later in the pipeline if needed
            total_chars = sum(
                len(str(msg.content or "")) for msg in final_request.messages
            )
            token_estimate = total_chars // 4  # ~4 chars per token average

            # Initialize config for exception handler
            config: CompactionConfig | None = None
            try:
                # Use injected config or default
                compaction_config: CompactionConfig
                if self._config and hasattr(self._config, "compaction"):
                    compaction_config = self._config.compaction
                else:
                    compaction_config = CompactionConfig.default()

                # Store for exception handler
                config = compaction_config

                # Check if we should even check compaction (token threshold)
                # First check: is feature enabled?
                # Second check: is token count above threshold?
                if (
                    compaction_config.enabled
                    and token_estimate >= compaction_config.token_threshold
                ):
                    compaction_result = (
                        await self._history_compaction_service.compact_history(
                            final_request.messages,
                            compaction_config,
                            current_token_estimate=token_estimate,
                        )
                    )
                    if compaction_result.was_compacted and logger.isEnabledFor(
                        logging.INFO
                    ):
                        # Use structured logging with observability context (Req 4.1)
                        logger.info(
                            "Compacted conversation history",
                            extra={
                                "original_messages": compaction_result.original_message_count,
                                "compacted_messages": compaction_result.compacted_count,
                                "bytes_saved": compaction_result.bytes_saved,
                                "tokens_saved_estimate": compaction_result.tokens_saved_estimate,
                                "original_tokens_estimate": token_estimate,
                                # Export metrics for observability (Req 4.1)
                                "metrics": compaction_result.to_metrics(),
                            },
                        )
                    if compaction_result.was_compacted:
                        final_request = final_request.model_copy(
                            update={"messages": compaction_result.messages}
                        )

                        # Check for overflow after compaction (Req 3.2)
                        # Calculate post-compaction token estimate
                        post_compaction_chars = sum(
                            len(str(msg.content or ""))
                            for msg in final_request.messages
                        )
                        post_compaction_estimate = post_compaction_chars // 4

                        budget = TokenBudgetConfig.from_config(
                            compaction_config, post_compaction_estimate
                        )
                        if budget.exceeds_max:
                            overflow = budget.current_estimate - budget.max_tokens
                            logger.warning(
                                "Context compaction could not reduce tokens below maximum - overflow risk",
                                extra={
                                    "current_estimate": budget.current_estimate,
                                    "max_tokens": budget.max_tokens,
                                    "overflow_tokens": overflow,
                                    "recommendation": "Consider adjusting compaction policies or token limits",
                                },
                            )
            except Exception as exc:
                # Fail-open: log error and continue with original messages
                if logger.isEnabledFor(logging.WARNING):
                    # Safely get config.enabled for logging, defaulting to False if config not available
                    config_enabled = False
                    if config is not None:
                        config_enabled = getattr(config, "enabled", False)
                    logger.warning(
                        "History compaction failed - continuing with original messages: %s",
                        exc,
                        exc_info=True,
                        extra={
                            "compaction": {
                                "failed_open": True,
                                "enabled": config_enabled,
                                "error": str(exc),
                            }
                        },
                    )

        # Return the (possibly modified) request
        return final_request

    @staticmethod
    def _message_has_content(message: Any) -> bool:
        """Check if a message has user content.

        Args:
            message: The message to check (can be dict, ChatMessage, or other)

        Returns:
            True if message has user role and non-empty content
        """
        role = (
            message.get("role")
            if isinstance(message, dict)
            else getattr(message, "role", None)
        )
        if role != "user":
            return False
        content = (
            message.get("content")
            if isinstance(message, dict)
            else getattr(message, "content", None)
        )
        if content is None:
            return False
        if isinstance(content, str):
            return bool(content.strip())  # Check for non-empty string
        if isinstance(content, list):
            return len(content) > 0
        return bool(content)

    @staticmethod
    def _extract_messages_from_command_result(result: Any) -> list[ChatMessage]:
        """Extract chat messages embedded in command results for backend replay.

        Args:
            result: Command result that may contain messages

        Returns:
            List of extracted ChatMessage instances
        """

        def _coerce_message(candidate: Any) -> ChatMessage | None:
            """Convert a candidate object into a ChatMessage when possible."""
            if isinstance(candidate, ChatMessage):
                return candidate

            if hasattr(candidate, "model_dump") and callable(candidate.model_dump):
                try:
                    dumped = candidate.model_dump()
                    if isinstance(dumped, dict):
                        return ChatMessage(**dumped)
                except (ValidationError, TypeError, ValueError) as e:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Failed to coerce object with model_dump to ChatMessage: %s",
                            e,
                            exc_info=True,
                        )
                    return None

            if isinstance(candidate, dict):
                try:
                    return ChatMessage(**candidate)
                except (ValidationError, TypeError, ValueError) as e:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Failed to coerce dict to ChatMessage: %s",
                            e,
                            exc_info=True,
                        )
                    return None
            return None

        def _iter_candidates(value: Any) -> Iterable[Any]:
            """Yield potential message representations from arbitrary structures."""
            if value is None:
                return ()

            # Prefer explicit tool message containers if present
            if isinstance(value, dict):
                # Check for tool_messages key in dict
                if "tool_messages" in value:
                    tool_value = value["tool_messages"]
                    if isinstance(tool_value, list | tuple):
                        return tuple(tool_value)
                    if tool_value is not None:
                        return (tool_value,)
            elif hasattr(value, "tool_messages"):
                tool_value = value.tool_messages
                if isinstance(tool_value, list | tuple):
                    return tuple(tool_value)
                if tool_value is not None:
                    return (tool_value,)

            if isinstance(value, list | tuple):
                return tuple(value)

            return (value,)

        messages: list[ChatMessage] = []
        for candidate in _iter_candidates(result):
            coerced = _coerce_message(candidate)
            if coerced is not None:
                messages.append(coerced)
        return messages
