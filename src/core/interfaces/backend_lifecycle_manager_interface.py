"""Interface for backend lifecycle manager.

Responsible for managing backend instance creation, caching, and shutdown.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.connectors.base import LLMBackend


class IBackendLifecycleManager(ABC):
    """Service interface for managing backend lifecycle."""

    @abstractmethod
    async def get_or_create(
        self, backend_type: str, session_id: str | None = None
    ) -> LLMBackend:
        """Get existing backend or create new one.

        Cache key rules:
        - With session_id: `f"{backend_type}:{session_id}"`
        - Special case gemini-cli-acp without session_id: `f"{backend_type}:default"`
        - Otherwise: `backend_type`

        Per-session cache is LRU via OrderedDict; eviction shuts down backends.
        Permanently disabled backends raise BackendError.

        Args:
            backend_type: The type of backend to get or create.
            session_id: Optional session ID for per-session backends.

        Returns:
            The backend instance.

        Raises:
            BackendError: If backend is permanently disabled.
        """

    @abstractmethod
    async def shutdown(self, backend: LLMBackend) -> None:
        """Shutdown backend with proper cleanup.

        Args:
            backend: The backend to shutdown.
        """

    @abstractmethod
    def discard(self, backend_type: str, session_id: str | None, reason: str) -> None:
        """Discard and disable a backend instance.

        Disables globally and removes both global and per-session variants.
        Records the disablement reason.

        Args:
            backend_type: The type of backend to discard.
            session_id: Optional session ID if it was a per-session backend.
            reason: The reason for disabling the backend.
        """

    @abstractmethod
    def is_disabled(self, backend_type: str) -> bool:
        """Check if backend is permanently disabled.

        Args:
            backend_type: The type of backend to check.

        Returns:
            True if backend is permanently disabled.
        """

    @abstractmethod
    def get_disabled_backends(self) -> dict[str, dict[str, Any]]:
        """Get the permanently disabled backend registry.

        The returned mapping is keyed by backend type and contains details like:
        - reason: str
        - timestamp: float
        """

    @abstractmethod
    def get_active_backends(self) -> dict[str, LLMBackend]:
        """Get all active backend instances.

        Returns:
            Dictionary mapping backend instance names to LLMBackend objects.
        """
