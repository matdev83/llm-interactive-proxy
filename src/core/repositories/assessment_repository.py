"""
Repository for managing assessment state persistence.

This module provides in-memory storage for session assessment state,
with automatic cleanup of expired sessions.
"""

import time

from src.core.domain.assessment import SessionAssessmentState
from src.core.interfaces.assessment_service_interface import IAssessmentRepository


class InMemoryAssessmentRepository(IAssessmentRepository):
    """
    In-memory implementation of assessment repository.

    This provides session state management with automatic cleanup
    of expired sessions to prevent memory leaks.
    """

    def __init__(self, cleanup_interval: int = 3600):
        """
        Initialize repository.

        Args:
            cleanup_interval: Interval in seconds between automatic cleanups
        """
        self._states: dict[str, SessionAssessmentState] = {}
        self._cleanup_interval = cleanup_interval
        self._last_cleanup = time.time()

    def get_session_state(self, session_id: str) -> SessionAssessmentState:
        """
        Get assessment state for a session.

        Creates a new state if one doesn't exist for the session.
        Also triggers cleanup if enough time has passed.

        Args:
            session_id: Unique identifier for the session

        Returns:
            SessionAssessmentState for the session
        """
        # Periodic cleanup
        if time.time() - self._last_cleanup > self._cleanup_interval:
            self.cleanup_expired_sessions()

        if session_id not in self._states:
            self._states[session_id] = SessionAssessmentState(session_id=session_id)

        return self._states[session_id]

    def update_session_state(
        self, state: SessionAssessmentState, update_timestamp: bool = True
    ):
        """
        Update assessment state for a session.

        Args:
            state: Updated session assessment state
            update_timestamp: Whether to update the timestamp (useful for testing)
        """
        if update_timestamp:
            state.update_timestamp()
        self._states[state.session_id] = state

    def delete_session_state(self, session_id: str):
        """
        Delete assessment state for a session.

        Args:
            session_id: Unique identifier for the session
        """
        if session_id in self._states:
            del self._states[session_id]

    def cleanup_expired_sessions(self, max_age_seconds: int = 3600):
        """
        Clean up expired session states.

        Args:
            max_age_seconds: Maximum age in seconds before cleanup
        """
        current_time = time.time()
        expired_sessions = [
            session_id
            for session_id, state in self._states.items()
            if current_time - state.last_updated > max_age_seconds
        ]

        for session_id in expired_sessions:
            del self._states[session_id]

        self._last_cleanup = current_time

        if expired_sessions:
            from src.core.common.logging_utils import get_logger

            logger = get_logger(__name__)
            logger.debug(
                f"Cleaned up {len(expired_sessions)} expired assessment sessions"
            )

    def get_all_session_ids(self) -> list[str]:
        """
        Get all active session IDs.

        Returns:
            List of session IDs
        """
        return list(self._states.keys())

    def get_stats(self) -> dict[str, int]:
        """
        Get repository statistics for monitoring.

        Returns:
            Dictionary with repository statistics
        """
        return {
            "total_sessions": len(self._states),
            "sessions_with_assessments": len(
                [state for state in self._states.values() if state.assessment_history]
            ),
            "total_assessments": sum(
                len(state.assessment_history) for state in self._states.values()
            ),
        }
