"""Interface for connection activity tracking.

This module defines the interface for tracking active connections
through backend connectors.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.domain.connection_activity import (
        BackendActivitySnapshot,
        ConnectionType,
        GlobalActivitySnapshot,
    )


class IConnectionActivityTracker(ABC):
    """Interface for tracking connection activity through backend connectors.

    Implementations must be thread-safe as connections may be tracked
    from multiple async tasks concurrently.
    """

    @abstractmethod
    @contextmanager
    def track_connection(
        self,
        session_id: str,
        backend_name: str,
        connection_type: ConnectionType,
        model: str | None = None,
    ) -> Generator[None, None, None]:
        """Context manager to track a connection's lifecycle.

        The connection is automatically registered when entering the context
        and unregistered when exiting (even on exception).

        Args:
            session_id: Unique identifier for the session/request.
            backend_name: Name of the backend instance.
            connection_type: Whether streaming or non-streaming.
            model: The model being used (optional).

        Yields:
            None - the connection is tracked in the background.
        """

    @abstractmethod
    def increment_rx(self, session_id: str, backend_name: str, byte_count: int) -> None:
        """Increment the received bytes counter for a connection.

        Args:
            session_id: The session identifier.
            backend_name: The backend instance name.
            byte_count: Number of bytes received.
        """

    @abstractmethod
    def increment_tx(self, session_id: str, backend_name: str, byte_count: int) -> None:
        """Increment the transmitted bytes counter for a connection.

        Args:
            session_id: The session identifier.
            backend_name: The backend instance name.
            byte_count: Number of bytes transmitted.
        """

    @abstractmethod
    def get_backend_snapshot(self, backend_name: str) -> BackendActivitySnapshot:
        """Get activity snapshot for a specific backend.

        Args:
            backend_name: The backend instance name.

        Returns:
            Snapshot of current activity for the backend.
        """

    @abstractmethod
    def get_global_snapshot(self) -> GlobalActivitySnapshot:
        """Get global activity snapshot across all backends.

        Returns:
            Snapshot of current activity across all backends.
        """

    @abstractmethod
    def cleanup_stale_connections(self) -> int:
        """Remove connections that have exceeded the stale timeout.

        This can be called periodically to clean up orphaned connections
        that were not properly closed (e.g., due to crashes).

        Returns:
            Number of connections removed.
        """
