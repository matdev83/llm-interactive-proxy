"""Interface for planning phase manager.

Responsible for managing planning phase model overrides and counter tracking.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class IPlanningPhaseManager(ABC):
    """Service interface for managing planning phase lifecycle."""

    @abstractmethod
    async def apply_if_needed(self, session: Any, default_backend: str) -> None:
        """Apply planning phase model override if conditions are met.

        Enabled only when `session.state.planning_phase_config.enabled`
        and `strong_model` are set. Original route is persisted only once
        per planning phase.

        Args:
            session: The current session.
            default_backend: Default backend for model parsing.
        """

    @abstractmethod
    async def update_counters(self, session_id: str, response: Any) -> None:
        """Update planning phase counters after a successful completion.

        When max turns or file writes are reached, restores original
        backend/model and clears original-route fields.

        Args:
            session_id: The session ID.
            response: The response envelope containing metadata.
        """

    @abstractmethod
    def count_file_writes(self, response: Any) -> int:
        """Count file write tool calls in a response.

        Args:
            response: The response envelope.

        Returns:
            Number of file write operations detected.
        """
