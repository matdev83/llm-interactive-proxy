"""
Repository for managing assessment state persistence.

This module provides in-memory storage for session assessment state,
with automatic cleanup of expired sessions.
"""

import time
from threading import RLock

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
        self._lock = RLock()

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
        normalized_id = self._normalize_session_id(session_id)

        with self._lock:
            if time.time() - self._last_cleanup > self._cleanup_interval:
                self._cleanup_locked()

            state = self._states.get(normalized_id)
            if state is None:
                state = SessionAssessmentState(session_id=normalized_id)
                self._states[normalized_id] = state
            return state

    def update_session_state(
        self, state: SessionAssessmentState, update_timestamp: bool = True
    ):
        """
        Update assessment state for a session.

        Args:
            state: Updated session assessment state
            update_timestamp: Whether to update the timestamp (useful for testing)
        """
        with self._lock:
            if update_timestamp:
                state.update_timestamp()
            self._states[state.session_id] = state

    def delete_session_state(self, session_id: str):
        """
        Delete assessment state for a session.

        Args:
            session_id: Unique identifier for the session
        """
        normalized_id = self._normalize_session_id(session_id)
        with self._lock:
            self._states.pop(normalized_id, None)

    def cleanup_expired_sessions(self, max_age_seconds: int = 3600):
        """
        Clean up expired session states.

        Args:
            max_age_seconds: Maximum age in seconds before cleanup
        """
        with self._lock:
            self._cleanup_locked(max_age_seconds)

    def get_all_session_ids(self) -> list[str]:
        """
        Get all active session IDs.

        Returns:
            List of session IDs
        """
        with self._lock:
            return list(self._states.keys())

    def get_stats(self) -> dict[str, int]:
        """
        Get repository statistics for monitoring.

        Returns:
            Dictionary with repository statistics
        """
        with self._lock:
            return {
                "total_sessions": len(self._states),
                "sessions_with_assessments": len(
                    [
                        state
                        for state in self._states.values()
                        if state.assessment_history
                    ]
                ),
                "total_assessments": sum(
                    len(state.assessment_history) for state in self._states.values()
                ),
            }

    def _normalize_session_id(self, session_id: str) -> str:
        if not session_id or not str(session_id).strip():
            raise ValueError("session_id must be a non-empty string")
        return str(session_id)

    def _cleanup_locked(self, max_age_seconds: int = 3600) -> int:
        current_time = time.time()
        expired_sessions = [
            session_id
            for session_id, state in self._states.items()
            if current_time - state.last_updated > max_age_seconds
        ]

        for session_id in expired_sessions:
            del self._states[session_id]

        self._last_cleanup = current_time
        return len(expired_sessions)
