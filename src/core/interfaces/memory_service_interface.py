"""Interface for the Memory Service.

Defines the protocol for memory operations including session memory state management,
interaction capture, and session completion handling.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from src.core.memory.models import CapturedInteraction


class IMemoryService(Protocol):
    """Protocol for memory service operations.

    The memory service manages cross-session context persistence by:
    - Tracking memory activation state per session
    - Capturing interactions during enabled sessions
    - Triggering summary generation on session completion
    - Providing access controls based on user/client identity
    """

    def is_available(self) -> bool:
        """Check if the memory feature is globally available.

        Returns:
            True if memory is enabled in global configuration.
        """
        ...

    async def is_enabled_for_session(self, session_id: str) -> bool:
        """Check if memory capture is enabled for a specific session.

        Args:
            session_id: The session identifier.

        Returns:
            True if memory is currently enabled for this session.
        """
        ...

    async def enable_for_session(
        self,
        session_id: str,
        user_id: str,
        *,
        client_id: str | None = None,
        tenant_id: str | None = None,
        project_root: str | None = None,
    ) -> bool:
        """Enable memory capture for a session.

        Args:
            session_id: The session identifier.
            user_id: The user identifier (required for multi-user mode).
            client_id: Optional client agent identifier.
            tenant_id: Optional tenant identifier.
            project_root: Optional project root path.

        Returns:
            True if memory was successfully enabled.
            False if memory is unavailable or user/client is denied.
        """
        ...

    async def disable_for_session(self, session_id: str) -> None:
        """Disable memory capture for a session.

        Args:
            session_id: The session identifier.
        """
        ...

    async def capture_interaction(
        self,
        session_id: str,
        interaction: CapturedInteraction,
    ) -> bool:
        """Capture an interaction for a session.

        Args:
            session_id: The session identifier.
            interaction: The interaction to capture.

        Returns:
            True if captured successfully, False if buffer full or not enabled.
        """
        ...

    async def record_tool_event(self, session_id: str, event: Any) -> bool:
        """Record a deterministic tool event (file edit or git commit) for a session."""
        ...

    async def mark_session_complete(
        self,
        session_id: str,
        *,
        backend_model: str | None = None,
        branch: str | None = None,
        head_sha: str | None = None,
        termination_reason: str | None = None,
    ) -> bool:
        """Mark a session as complete and queue for summary generation.

        Args:
            session_id: The session identifier.
            backend_model: The backend:model used for the session.
            branch: Optional git branch name.
            head_sha: Optional git HEAD SHA.
            termination_reason: Optional termination reason (e.g., client termination reason).

        Returns:
            True if session was queued for summarization.
            False if session was not enabled or already queued.
        """
        ...

    async def get_captured_tool_events(self, session_id: str) -> Any:
        """Get deterministic tool events (file edits and git commits) for a session."""
        ...

    async def get_session_user_id(self, session_id: str) -> str | None:
        """Get the user ID associated with a session.

        Args:
            session_id: The session identifier.

        Returns:
            The user ID if session is enabled, None otherwise.
        """
        ...

    async def get_session_project_root(self, session_id: str) -> str | None:
        """Get the project root associated with a session.

        Args:
            session_id: The session identifier.

        Returns:
            The project root if available, None otherwise.
        """
        ...

    async def get_session_state(self, session_id: str) -> Any | None:
        """Get the full session state.

        Args:
            session_id: The session identifier.

        Returns:
            The session state if available, None otherwise.
        """
        ...
