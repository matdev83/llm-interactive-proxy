"""Thread-safe connection activity tracker service.

This module provides real-time tracking of active connections through
backend connectors with RX/TX byte counters per session.

The implementation uses threading.Lock for atomic operations to ensure
thread safety without significant performance impact.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from src.core.domain.connection_activity import (
    BackendActivitySnapshot,
    ConnectionActivity,
    ConnectionType,
    GlobalActivitySnapshot,
)
from src.core.interfaces.activity_tracker_interface import IConnectionActivityTracker

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ConnectionActivityTracker(IConnectionActivityTracker):
    """Thread-safe tracker for active backend connections.

    This service tracks currently transmitting connections through backend
    connectors, providing real-time visibility into RX/TX activity.

    Thread Safety:
        All public methods are thread-safe using a single lock for atomic
        operations. The lock is held briefly for each operation to minimize
        contention.

    Performance:
        - Counter updates are O(1) dictionary lookups + integer addition
        - Snapshots create shallow copies to avoid lock contention during
          serialization
        - No per-chunk logging unless DEBUG level is enabled
    """

    def __init__(self, stale_timeout_seconds: float = 300.0) -> None:
        """Initialize the activity tracker.

        Args:
            stale_timeout_seconds: Timeout after which orphaned connections
                are considered stale and eligible for cleanup (default 5 min).
        """
        self._lock = threading.Lock()
        # Key: (backend_name, session_id) -> ConnectionActivity
        self._connections: dict[tuple[str, str], ConnectionActivity] = {}
        self._stale_timeout = stale_timeout_seconds

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
        key = (backend_name, session_id)
        activity = ConnectionActivity(
            session_id=session_id,
            backend_name=backend_name,
            connection_type=connection_type,
            model=model,
        )

        with self._lock:
            self._connections[key] = activity

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Started tracking connection: backend=%s, session=%s, type=%s",
                backend_name,
                session_id,
                connection_type.value,
            )

        try:
            yield
        finally:
            with self._lock:
                removed = self._connections.pop(key, None)

            if logger.isEnabledFor(logging.DEBUG) and removed:
                logger.debug(
                    "Stopped tracking connection: backend=%s, session=%s, "
                    "duration=%.3fs, rx=%d, tx=%d",
                    backend_name,
                    session_id,
                    removed.duration_seconds,
                    removed.bytes_rx,
                    removed.bytes_tx,
                )

    def increment_rx(self, session_id: str, backend_name: str, byte_count: int) -> None:
        """Increment the received bytes counter for a connection.

        Args:
            session_id: The session identifier.
            backend_name: The backend instance name.
            byte_count: Number of bytes received.
        """
        if byte_count <= 0:
            return

        key = (backend_name, session_id)
        with self._lock:
            conn = self._connections.get(key)
            if conn:
                conn.bytes_rx += byte_count

    def increment_tx(self, session_id: str, backend_name: str, byte_count: int) -> None:
        """Increment the transmitted bytes counter for a connection.

        Args:
            session_id: The session identifier.
            backend_name: The backend instance name.
            byte_count: Number of bytes transmitted.
        """
        if byte_count <= 0:
            return

        key = (backend_name, session_id)
        with self._lock:
            conn = self._connections.get(key)
            if conn:
                conn.bytes_tx += byte_count

    def get_backend_snapshot(self, backend_name: str) -> BackendActivitySnapshot:
        """Get activity snapshot for a specific backend.

        Args:
            backend_name: The backend instance name.

        Returns:
            Snapshot of current activity for the backend.
        """
        with self._lock:
            connections = [
                ConnectionActivity(
                    session_id=conn.session_id,
                    backend_name=conn.backend_name,
                    connection_type=conn.connection_type,
                    started_at=conn.started_at,
                    model=conn.model,
                    bytes_rx=conn.bytes_rx,
                    bytes_tx=conn.bytes_tx,
                )
                for (bname, _), conn in self._connections.items()
                if bname == backend_name
            ]

        total_rx = sum(c.bytes_rx for c in connections)
        total_tx = sum(c.bytes_tx for c in connections)

        return BackendActivitySnapshot(
            backend_name=backend_name,
            active_connections=len(connections),
            connections=connections,
            total_bytes_rx=total_rx,
            total_bytes_tx=total_tx,
        )

    def get_global_snapshot(self) -> GlobalActivitySnapshot:
        """Get global activity snapshot across all backends.

        Returns:
            Snapshot of current activity across all backends.
        """
        with self._lock:
            # Create copies of all connections to avoid lock during processing
            all_connections = [
                ConnectionActivity(
                    session_id=conn.session_id,
                    backend_name=conn.backend_name,
                    connection_type=conn.connection_type,
                    started_at=conn.started_at,
                    model=conn.model,
                    bytes_rx=conn.bytes_rx,
                    bytes_tx=conn.bytes_tx,
                )
                for conn in self._connections.values()
            ]

        # Group by backend
        backends_map: dict[str, list[ConnectionActivity]] = {}
        for conn in all_connections:
            if conn.backend_name not in backends_map:
                backends_map[conn.backend_name] = []
            backends_map[conn.backend_name].append(conn)

        # Build snapshots
        backend_snapshots = []
        total_rx = 0
        total_tx = 0

        for backend_name, connections in backends_map.items():
            backend_rx = sum(c.bytes_rx for c in connections)
            backend_tx = sum(c.bytes_tx for c in connections)
            total_rx += backend_rx
            total_tx += backend_tx

            backend_snapshots.append(
                BackendActivitySnapshot(
                    backend_name=backend_name,
                    active_connections=len(connections),
                    connections=connections,
                    total_bytes_rx=backend_rx,
                    total_bytes_tx=backend_tx,
                )
            )

        return GlobalActivitySnapshot(
            timestamp=time.time(),
            backends=backend_snapshots,
            total_active_connections=len(all_connections),
            total_bytes_rx=total_rx,
            total_bytes_tx=total_tx,
        )

    def cleanup_stale_connections(self) -> int:
        """Remove connections that have exceeded the stale timeout.

        This can be called periodically to clean up orphaned connections
        that were not properly closed (e.g., due to crashes).

        Returns:
            Number of connections removed.
        """
        now = time.time()
        stale_keys = []

        with self._lock:
            for key, conn in self._connections.items():
                if now - conn.started_at > self._stale_timeout:
                    stale_keys.append(key)

            for key in stale_keys:
                del self._connections[key]

        if stale_keys and logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Cleaned up %d stale connections (timeout=%.0fs)",
                len(stale_keys),
                self._stale_timeout,
            )

        return len(stale_keys)

    def get_connection_count(self) -> int:
        """Get the total number of active connections.

        Returns:
            Number of currently tracked connections.
        """
        with self._lock:
            return len(self._connections)

    def clear(self) -> None:
        """Clear all tracked connections.

        This is primarily useful for testing.
        """
        with self._lock:
            self._connections.clear()


# Global singleton instance
_global_tracker: ConnectionActivityTracker | None = None
_global_lock = threading.Lock()


def get_activity_tracker() -> ConnectionActivityTracker:
    """Get the global activity tracker instance.

    Returns:
        The global ConnectionActivityTracker singleton.
    """
    global _global_tracker
    if _global_tracker is None:
        with _global_lock:
            if _global_tracker is None:
                _global_tracker = ConnectionActivityTracker()
    return _global_tracker


def reset_activity_tracker() -> None:
    """Reset the global activity tracker.

    This is primarily useful for testing.
    """
    global _global_tracker
    with _global_lock:
        if _global_tracker is not None:
            _global_tracker.clear()
        _global_tracker = None
