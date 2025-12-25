"""
Connection Manager for Codebuff WebSocket connections.

This module manages WebSocket connections, session state, and subscriptions
for Codebuff clients.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from src.codebuff.exceptions import CodebuffSessionError
from src.codebuff.schemas import SessionState

if TYPE_CHECKING:
    from fastapi import WebSocket


logger = logging.getLogger(__name__)

# Maximum number of connections to prevent unbounded memory growth
# This limit prevents memory leaks when connections aren't properly cleaned up
_MAX_CONNECTIONS = 10000


class ConnectionManager:
    """Manages WebSocket connections and sessions for Codebuff clients.

    This class tracks active connections, maintains session state, monitors
    heartbeats, and manages topic subscriptions.
    """

    def __init__(
        self,
        heartbeat_timeout_seconds: int = 60,
        max_connections: int = _MAX_CONNECTIONS,
    ) -> None:
        """Initialize the connection manager.

        Args:
            heartbeat_timeout_seconds: Timeout in seconds for heartbeat monitoring.
                Connections that haven't sent a ping within this time will be
                terminated.
            max_connections: Maximum number of concurrent connections to track.
                            Prevents unbounded memory growth when connections
                            aren't properly cleaned up. Default: 10000
        """
        self._connections: dict[WebSocket, SessionState] = {}
        self._session_id_to_websocket: dict[str, WebSocket] = {}
        self._subscriptions: dict[str, set[WebSocket]] = {}
        self._heartbeat_timeout = timedelta(seconds=heartbeat_timeout_seconds)
        self._max_connections = max_connections
        self._lock = asyncio.Lock()
        logger.info(
            "ConnectionManager initialized with heartbeat timeout: %d seconds, "
            "max_connections: %d",
            heartbeat_timeout_seconds,
            max_connections,
        )

    @staticmethod
    def _safe(value: object) -> str:
        """Convert potentially invalid strings to safe UTF-8 for logging."""
        try:
            return (
                str(value)
                .encode("utf-8", errors="replace")
                .decode("utf-8", errors="replace")
            )
        except (TypeError, UnicodeError) as e:
            logger.debug("Failed to sanitize value for logging: %s", e)
            return repr(value)

    async def connect(self, websocket: WebSocket, session_id: str) -> None:
        """Register a new WebSocket connection.

        Creates a new session for the connection and tracks it.

        Args:
            websocket: The WebSocket connection to register.
            session_id: The client-provided session ID.

        Raises:
            CodebuffSessionError: If the session ID is already in use or max connections reached.
        """
        async with self._lock:
            if session_id in self._session_id_to_websocket:
                logger.warning(
                    "Attempted to register duplicate session ID: %s",
                    self._safe(session_id),
                )
                raise CodebuffSessionError(
                    f"Session ID {session_id} is already in use",
                    details={"session_id": session_id},
                )

            # Check if we're at max connections and try to clean up stale ones
            if len(self._connections) >= self._max_connections:
                logger.warning(
                    "Max connections (%d) reached. Attempting to clean up stale connections...",
                    self._max_connections,
                )
                # Try to clean up stale connections synchronously (best effort)
                # Note: This is a best-effort cleanup; full cleanup requires async context
                now = datetime.utcnow()
                stale_websockets = [
                    ws
                    for ws, session in self._connections.items()
                    if (now - session.last_seen) > self._heartbeat_timeout
                ]

                # Attempt to disconnect stale connections
                # If any fail, we still enforce the limit strictly
                disconnected_count = 0
                for stale_ws in stale_websockets:
                    try:
                        # Disconnect synchronously (removes from dicts)
                        self._disconnect_locked(stale_ws)
                        disconnected_count += 1
                    except Exception as e:
                        logger.warning(
                            "Failed to disconnect stale connection during cleanup: %s",
                            str(e),
                            exc_info=True,
                        )

                # Strict enforcement: reject if still at limit after cleanup attempt
                if len(self._connections) >= self._max_connections:
                    logger.error(
                        "Cannot register new connection: max_connections (%d) reached "
                        "after cleanup attempt (disconnected %d stale connections, "
                        "%d connections remaining)",
                        self._max_connections,
                        disconnected_count,
                        len(self._connections),
                    )
                    raise CodebuffSessionError(
                        f"Maximum connections ({self._max_connections}) reached",
                        details={"max_connections": self._max_connections},
                    )

            now = datetime.utcnow()
            session = SessionState(
                session_id=session_id,
                created_at=now,
                last_seen=now,
            )

            self._connections[websocket] = session
            self._session_id_to_websocket[session_id] = websocket

            logger.info("Connection registered: session_id=%s", self._safe(session_id))

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a connection and clean up its session.

        Removes the connection from tracking, cleans up subscriptions,
        and removes the session state.

        Args:
            websocket: The WebSocket connection to remove.
        """
        async with self._lock:
            self._disconnect_locked(websocket)

    def _disconnect_locked(self, websocket: WebSocket) -> None:
        """Remove a connection without acquiring lock (must already hold lock).

        Args:
            websocket: The WebSocket connection to remove.
        """
        session = self._connections.get(websocket)
        if session is None:
            logger.warning("Attempted to disconnect unknown connection")
            return

        session_id = session.session_id

        # Remove from session ID mapping
        if session_id in self._session_id_to_websocket:
            del self._session_id_to_websocket[session_id]

        # Remove all subscriptions for this connection
        for topic in list(session.subscriptions):
            if topic in self._subscriptions:
                self._subscriptions[topic].discard(websocket)
                if not self._subscriptions[topic]:
                    del self._subscriptions[topic]

        # Remove the connection
        del self._connections[websocket]

        logger.info("Connection disconnected: session_id=%s", self._safe(session_id))

    async def get_session(self, websocket: WebSocket) -> SessionState | None:
        """Get session data for a connection.

        Args:
            websocket: The WebSocket connection to look up.

        Returns:
            The session state for the connection, or None if not found.
        """
        async with self._lock:
            return self._connections.get(websocket)

    async def update_last_seen(self, websocket: WebSocket) -> None:
        """Update the last-seen timestamp for a connection.

        This is called when a ping message is received to track heartbeats.

        Args:
            websocket: The WebSocket connection to update.

        Raises:
            CodebuffSessionError: If the connection is not found.
        """
        async with self._lock:
            session = self._connections.get(websocket)
            if session is None:
                logger.warning("Attempted to update last_seen for unknown connection")
                raise CodebuffSessionError(
                    "Connection not found",
                    details={"error": "Connection not registered"},
                )

            session.last_seen = datetime.utcnow()
            logger.debug(
                "Updated last_seen for session: %s", self._safe(session.session_id)
            )

    async def subscribe(self, websocket: WebSocket, topics: list[str]) -> None:
        """Add subscriptions for a connection.

        Args:
            websocket: The WebSocket connection to subscribe.
            topics: List of topic names to subscribe to.

        Raises:
            CodebuffSessionError: If the connection is not found.
        """
        async with self._lock:
            session = self._connections.get(websocket)
            if session is None:
                logger.warning("Attempted to subscribe unknown connection")
                raise CodebuffSessionError(
                    "Connection not found",
                    details={"error": "Connection not registered"},
                )

            for topic in topics:
                # Add to session's subscription set
                session.subscriptions.add(topic)

                # Add to topic's subscriber set
                if topic not in self._subscriptions:
                    self._subscriptions[topic] = set()
                self._subscriptions[topic].add(websocket)

            logger.info(
                "Subscribed session %s to topics: %s",
                self._safe(session.session_id),
                ", ".join(topics),
            )

    async def unsubscribe(self, websocket: WebSocket, topics: list[str]) -> None:
        """Remove subscriptions for a connection.

        Args:
            websocket: The WebSocket connection to unsubscribe.
            topics: List of topic names to unsubscribe from.

        Raises:
            CodebuffSessionError: If the connection is not found.
        """
        async with self._lock:
            session = self._connections.get(websocket)
            if session is None:
                logger.warning("Attempted to unsubscribe unknown connection")
                raise CodebuffSessionError(
                    "Connection not found",
                    details={"error": "Connection not registered"},
                )

            for topic in topics:
                # Remove from session's subscription set
                session.subscriptions.discard(topic)

                # Remove from topic's subscriber set
                if topic in self._subscriptions:
                    self._subscriptions[topic].discard(websocket)
                    # Clean up empty topic sets
                    if not self._subscriptions[topic]:
                        del self._subscriptions[topic]

            logger.info(
                "Unsubscribed session %s from topics: %s",
                self._safe(session.session_id),
                ", ".join(topics),
            )

    async def get_subscribers(self, topic: str) -> list[WebSocket]:
        """Get all connections subscribed to a topic.

        Args:
            topic: The topic name to look up.

        Returns:
            List of WebSocket connections subscribed to the topic.
        """
        async with self._lock:
            return list(self._subscriptions.get(topic, set()))

    async def cleanup_stale_connections(self) -> None:
        """Terminate connections that haven't sent a ping recently.

        This method should be called periodically to clean up stale connections
        that have exceeded the heartbeat timeout.

        Returns:
            None. Stale connections are closed and removed.
        """
        async with self._lock:
            now = datetime.utcnow()
            stale_connections: list[tuple[WebSocket, str]] = []

            # Find stale connections
            for websocket, session in self._connections.items():
                time_since_last_seen = now - session.last_seen
                if time_since_last_seen > self._heartbeat_timeout:
                    stale_connections.append((websocket, session.session_id))

            # Close and remove stale connections
            for websocket, session_id in stale_connections:
                logger.warning(
                    "Closing stale connection: session_id=%s, last_seen=%s",
                    self._safe(session_id),
                    self._connections.get(websocket, None)
                    and self._connections[websocket].last_seen,
                )
                try:
                    await websocket.close(code=1000, reason="Heartbeat timeout")
                except Exception as e:
                    logger.error(
                        "Error closing stale connection %s: %s",
                        self._safe(session_id),
                        str(e),
                        exc_info=True,
                    )
                finally:
                    # Always clean up the connection state, even if close() failed
                    # This ensures we don't leak connections when websocket.close() fails
                    try:
                        self._disconnect_locked(websocket)
                    except Exception as e:
                        logger.error(
                            "Error disconnecting stale connection %s: %s",
                            self._safe(session_id),
                            str(e),
                            exc_info=True,
                        )
                        # Force removal from dicts if disconnect() fails
                        if websocket in self._connections:
                            session = self._connections[websocket]
                            if session.session_id in self._session_id_to_websocket:
                                del self._session_id_to_websocket[session.session_id]
                            del self._connections[websocket]
                            # Clean up subscriptions
                            for topic in list(session.subscriptions):
                                if topic in self._subscriptions:
                                    self._subscriptions[topic].discard(websocket)
                                    if not self._subscriptions[topic]:
                                        del self._subscriptions[topic]

            if stale_connections:
                logger.info("Cleaned up %d stale connections", len(stale_connections))

            # Enforce max_connections limit strictly after cleanup
            # This prevents growth beyond limit even if some connections couldn't be cleaned
            if len(self._connections) > self._max_connections:
                excess = len(self._connections) - self._max_connections
                logger.warning(
                    "Connection count (%d) exceeds max_connections (%d) after cleanup. "
                    "Evicting %d oldest connections.",
                    len(self._connections),
                    self._max_connections,
                    excess,
                )
                # Evict oldest connections by last_seen
                connections_by_age = sorted(
                    self._connections.items(), key=lambda x: x[1].last_seen
                )
                for websocket, _ in connections_by_age[:excess]:
                    try:
                        await websocket.close(
                            code=1000, reason="Max connections exceeded"
                        )
                    except Exception:
                        pass
                    finally:
                        self._disconnect_locked(websocket)
