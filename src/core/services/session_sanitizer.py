"""
Session sanitization service for mid-session backend switches.

This module provides functionality to clean backend-specific metadata
from session message history when switching between incompatible backends.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

from src.connectors.gemini_base.backend_compatibility import (
    requires_signature_cleanup,
)
from src.connectors.gemini_base.thought_signature_service import (
    ThoughtSignatureService,
    get_default_thought_signature_service,
)
from src.core.domain.chat import ChatMessage

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


class SessionSanitizer:
    """Sanitizes session data when backend changes require cleanup.

    When switching between incompatible Gemini backends (e.g., from
    gemini-oauth-plan to antigravity-oauth), thought signatures
    in session history become invalid and must be removed.

    This service:
    1. Detects when sanitization is needed based on backend compatibility
    2. Strips thought signatures from message history
    3. Clears the signature cache for the session
    """

    def __init__(
        self,
        thought_signature_service: ThoughtSignatureService | None = None,
    ) -> None:
        """Initialize the session sanitizer.

        Args:
            thought_signature_service: Optional service for thought signature
                management. If not provided, uses the default global service.
        """
        self._signature_service = (
            thought_signature_service or get_default_thought_signature_service()
        )

    def should_sanitize(
        self,
        previous_backend: str | None,
        new_backend: str | None,
    ) -> bool:
        """Determine if sanitization is needed for this backend switch.

        Args:
            previous_backend: The backend type used in the previous request
            new_backend: The backend type for the current request

        Returns:
            True if session data should be sanitized
        """
        return requires_signature_cleanup(previous_backend, new_backend)

    def sanitize_messages(
        self,
        messages: Sequence[ChatMessage],
    ) -> list[ChatMessage]:
        """Remove backend-specific metadata from message history.

        This strips thought signatures from tool calls in assistant messages
        while preserving all other message content.

        Args:
            messages: The message history to sanitize

        Returns:
            New list of messages with signatures removed
        """
        sanitized: list[ChatMessage] = []

        for message in messages:
            sanitized.append(self._sanitize_message(message))

        return sanitized

    def _sanitize_message(self, message: ChatMessage) -> ChatMessage:
        """Sanitize a single message if needed.

        Args:
            message: The message to sanitize

        Returns:
            Sanitized message (may be the same object if no changes needed)
        """
        # Only assistant messages with tool_calls need sanitization
        if message.role != "assistant":
            return message

        tool_calls = message.tool_calls
        if not tool_calls:
            return message

        # Sanitize tool calls
        sanitized_tool_calls: list[Any] = []
        modified = False

        for tc in tool_calls:
            sanitized_tc = self._sanitize_tool_call(tc)
            if sanitized_tc is not tc:
                modified = True
            sanitized_tool_calls.append(sanitized_tc)

        if not modified:
            return message

        # Create new message with sanitized tool_calls
        return ChatMessage(
            role=message.role,
            content=message.content,
            tool_calls=sanitized_tool_calls,
            tool_call_id=message.tool_call_id,
            name=message.name,
        )

    def _sanitize_tool_call(self, tc: Any) -> Any:
        """Sanitize a single tool call by removing thought signature.

        Args:
            tc: The tool call object (ToolCall or dict)

        Returns:
            Sanitized tool call (may be the same object if no changes needed)
        """
        extra_content = None

        # Handle both dict and ToolCall objects
        if isinstance(tc, dict):
            extra_content = tc.get("extra_content")
        elif hasattr(tc, "extra_content"):
            extra_content = tc.extra_content

        if not extra_content:
            return tc

        # Check for google.thought_signature
        if isinstance(extra_content, dict):
            google_extra = extra_content.get("google")
            if isinstance(google_extra, dict) and "thought_signature" in google_extra:
                # Need to remove the signature
                return self._create_sanitized_tool_call(tc)

        return tc

    def _create_sanitized_tool_call(self, tc: Any) -> Any:
        """Create a copy of the tool call without thought signature.

        Args:
            tc: The original tool call

        Returns:
            New tool call with thought signature removed
        """
        if isinstance(tc, dict):
            # Deep copy the dict and remove signature
            new_tc = dict(tc)
            new_extra = dict(tc.get("extra_content", {}))
            new_google = dict(new_extra.get("google", {}))
            new_google.pop("thought_signature", None)

            if new_google:
                new_extra["google"] = new_google
            else:
                new_extra.pop("google", None)

            if new_extra:
                new_tc["extra_content"] = new_extra
            else:
                new_tc.pop("extra_content", None)

            return new_tc

        # Handle ToolCall objects
        from src.core.domain.chat import ToolCall

        if isinstance(tc, ToolCall):
            tc_extra: dict[str, Any] | None = None

            if tc.extra_content:
                tc_extra = dict(tc.extra_content)
                if "google" in tc_extra:
                    tc_google = dict(tc_extra["google"])
                    tc_google.pop("thought_signature", None)
                    if tc_google:
                        tc_extra["google"] = tc_google
                    else:
                        del tc_extra["google"]

                if not tc_extra:
                    tc_extra = None

            return ToolCall(
                id=tc.id,
                type=tc.type,
                function=tc.function,
                extra_content=tc_extra,
            )

        # Unknown type, return as-is
        return tc

    def clear_signature_cache(self, session_id: str) -> int:
        """Clear cached thought signatures for the session.

        Args:
            session_id: The session ID to clear signatures for

        Returns:
            Number of entries cleared
        """
        return self._signature_service.clear_session_cache(session_id)

    def sanitize_session(
        self,
        messages: Sequence[ChatMessage],
        session_id: str,
        previous_backend: str | None,
        new_backend: str | None,
    ) -> tuple[list[ChatMessage], bool]:
        """Perform complete session sanitization if needed.

        This is the main entry point that checks if sanitization is needed
        and performs all cleanup operations.

        Args:
            messages: The message history
            session_id: The session ID
            previous_backend: The backend type used previously
            new_backend: The new backend type

        Returns:
            Tuple of (sanitized_messages, was_sanitized)
        """
        if not self.should_sanitize(previous_backend, new_backend):
            return list(messages), False

        logger.info(
            "Sanitizing session %s for backend switch: %s -> %s",
            session_id[:8] if session_id else "none",
            previous_backend or "none",
            new_backend or "none",
        )

        # Clear signature cache
        cleared_count = self.clear_signature_cache(session_id)

        # Sanitize messages
        sanitized_messages = self.sanitize_messages(messages)

        logger.info(
            "Session sanitization complete: cleared %d cached signatures, "
            "processed %d messages",
            cleared_count,
            len(sanitized_messages),
        )

        return sanitized_messages, True


# Default instance for convenience
_default_sanitizer: SessionSanitizer | None = None
_default_sanitizer_lock = threading.Lock()


def get_default_session_sanitizer() -> SessionSanitizer:
    """Get the default session sanitizer instance."""
    global _default_sanitizer
    if _default_sanitizer is not None:
        return _default_sanitizer

    with _default_sanitizer_lock:
        if _default_sanitizer is None:
            _default_sanitizer = SessionSanitizer()

    return _default_sanitizer


__all__ = [
    "SessionSanitizer",
    "get_default_session_sanitizer",
]
