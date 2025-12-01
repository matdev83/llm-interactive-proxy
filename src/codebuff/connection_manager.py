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


class ConnectionManager:
    """Manages WebSocket connections and sessions for Codebuff clients.

    This class tracks active connections, maintains session state, monitors
    heartbeats, and manages topic subscriptions.
    """

    def __init__(self, heartbeat_timeout_seconds: int = 60) -> None:
        """Initialize the connection manager.

        Args:
            heartbeat_timeout_seconds: Timeout in seconds for heartbeat monitoring.
                Connections that haven't sent a ping within this time will be
                terminated.
        """
        self._connections: dict[WebSocket, SessionState] = {}
        self._session_id_to_websocket: dict[str, WebSocket] = {}
        self._subscriptions: dict[str, set[WebSocket]] = {}
        self._heartbeat_timeout = timedelta(seconds=heartbeat_timeout_seconds)
        self._lock = asyncio.Lock()
        logger.info(
            "ConnectionManager initialized with heartbeat timeout: %d seconds",
            heartbeat_timeout_seconds,
        )

    def connect(self, websocket: WebSocket, session_id: str) -> None:
        """Register a new WebSocket connection.

        Creates a new session for the connection and tracks it.

        Args:
            websocket: The WebSocket connection to register.
            session_id: The client-provided session ID.

        Raises:
            CodebuffSessionError: If the session ID is already in use.
        """
        if session_id in self._session_id_to_websocket:
            logger.warning(
                "Attempted to register duplicate session ID: %s", session_id
            )
            raise CodebuffSessionError(
                f"Session ID {session_id} is already in use",
                details={"session_id": session_id},
            )

        now = datetime.utcnow()
        session = SessionState(
            session_id=session_id,
            created_at=now,
            last_seen=now,
        )

        self._connections[websocket] = session
        self._session_id_to_websocket[session_id] = websocket

        logger.info("Connection registered: session_id=%s", session_id)

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a connection and clean up its session.

        Removes the connection from tracking, cleans up subscriptions,
        and removes the session state.

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

        logger.info("Connection disconnected: session_id=%s", session_id)

    def get_session(self, websocket: WebSocket) -> SessionState | None:
        """Get session data for a connection.

        Args:
            websocket: The WebSocket connection to look up.

        Returns:
            The session state for the connection, or None if not found.
        """
        return self._connections.get(websocket)

    def update_last_seen(self, websocket: WebSocket) -> None:
        """Update the last-seen timestamp for a connection.

        This is called when a ping message is received to track heartbeats.

        Args:
            websocket: The WebSocket connection to update.

        Raises:
            CodebuffSessionError: If the connection is not found.
        """
        session = self._connections.get(websocket)
        if session is None:
            logger.warning("Attempted to update last_seen for unknown connection")
            raise CodebuffSessionError(
                "Connection not found",
                details={"error": "Connection not registered"},
            )

        session.last_seen = datetime.utcnow()
        logger.debug("Updated last_seen for session: %s", session.session_id)

    def subscribe(self, websocket: WebSocket, topics: list[str]) -> None:
        """Add subscriptions for a connection.

        Args:
            websocket: The WebSocket connection to subscribe.
            topics: List of topic names to subscribe to.

        Raises:
            CodebuffSessionError: If the connection is not found.
        """
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
            session.session_id,
            ", ".join(topics),
        )

    def unsubscribe(self, websocket: WebSocket, topics: list[str]) -> None:
        """Remove subscriptions for a connection.

        Args:
            websocket: The WebSocket connection to unsubscribe.
            topics: List of topic names to unsubscribe from.

        Raises:
            CodebuffSessionError: If the connection is not found.
        """
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
            session.session_id,
            ", ".join(topics),
        )

    def get_subscribers(self, topic: str) -> list[WebSocket]:
        """Get all connections subscribed to a topic.

        Args:
            topic: The topic name to look up.

        Returns:
            List of WebSocket connections subscribed to the topic.
        """
        return list(self._subscriptions.get(topic, set()))

    async def cleanup_stale_connections(self) -> None:
        """Terminate connections that haven't sent a ping recently.

        This method should be called periodically to clean up stale connections
        that have exceeded the heartbeat timeout.

        Returns:
            None. Stale connections are closed and removed.
        """
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
                session_id,
                self._connections[websocket].last_seen,
            )
            try:
                await websocket.close(code=1000, reason="Heartbeat timeout")
            except Exception as e:
                logger.error(
                    "Error closing stale connection %s: %s",
                    session_id,
                    str(e),
                    exc_info=True,
                )
            finally:
                # Always clean up the connection state
                self.disconnect(websocket)

        if stale_connections:
            logger.info("Cleaned up %d stale connections", len(stale_connections))
