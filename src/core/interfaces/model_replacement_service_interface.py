"""Model replacement service interface.

This module defines the interface for the random model replacement service,
which enables probabilistic swapping of user-specified backend:model pairs
with alternative replacement pairs during a session.
"""

from __future__ import annotations

from typing import Protocol

from src.core.domain.replacement_state import ReplacementState
from src.core.domain.request_context import RequestContext


class IModelReplacementService(Protocol):
    """Interface for model replacement service.

    This service manages random model replacement, including:
    - Determining when to trigger replacement based on probability
    - Managing replacement state per session
    - Providing effective backend:model routing information
    - Handling turn-based replacement windows
    - Supporting opt-out mechanisms
    """

    def should_replace(
        self,
        session_id: str,
        request_context: RequestContext,
    ) -> bool:
        """Determine if replacement should be triggered for this request.

        Evaluates whether model replacement should activate based on:
        - Feature enabled status
        - Session-level disable flag
        - Request header opt-out
        - Current replacement state (already active)
        - Probability threshold

        Args:
            session_id: The session identifier
            request_context: The request context containing headers and state

        Returns:
            True if replacement should be triggered, False otherwise
        """
        ...

    def get_effective_backend_model(
        self,
        session_id: str,
        original_backend: str,
        original_model: str,
    ) -> tuple[str, str]:
        """Get the effective backend:model to use for this request.

        Returns the replacement backend:model if replacement is active,
        otherwise returns the original backend:model.

        Args:
            session_id: The session identifier
            original_backend: The user-specified backend name
            original_model: The user-specified model name

        Returns:
            Tuple of (backend, model) to use for the request
        """
        ...

    def complete_turn(self, session_id: str) -> None:
        """Mark a turn as complete and update replacement state.

        Decrements the turn counter if replacement is active. When the
        counter reaches zero, automatically deactivates replacement.

        Args:
            session_id: The session identifier
        """
        ...

    def get_state(self, session_id: str) -> ReplacementState:
        """Get current replacement state for a session.

        Returns the current replacement state, creating a new inactive
        state if none exists for the session.

        Args:
            session_id: The session identifier

        Returns:
            The replacement state for the session
        """
        ...

    def disable_for_session(self, session_id: str) -> None:
        """Disable replacement for a specific session.

        Marks the session as replacement-disabled and immediately
        deactivates any active replacement.

        Args:
            session_id: The session identifier
        """
        ...

    async def activate_replacement(
        self,
        session_id: str,
        original_backend: str,
        original_model: str,
    ) -> None:
        """Activate replacement for a session.

        Initializes replacement state with the configured replacement
        backend:model and turn count.

        Args:
            session_id: The session identifier
            original_backend: The user-specified backend name
            original_model: The user-specified model name
        """
        ...

    def cleanup_session(self, session_id: str) -> None:
        """Clean up state for an ended session.

        Removes session state from internal dictionaries to prevent
        unbounded memory growth. Should be called when a session ends.

        Args:
            session_id: The session identifier
        """
        ...
