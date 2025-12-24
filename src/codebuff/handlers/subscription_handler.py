"""
Subscription handler for Codebuff topic subscriptions.

This module handles subscribe and unsubscribe actions from Codebuff clients,
managing topic subscriptions through the connection manager.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.codebuff.exceptions import CodebuffError, CodebuffSessionError

if TYPE_CHECKING:
    from fastapi import WebSocket

    from src.codebuff.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)


class SubscriptionHandler:
    """Handles subscription actions from Codebuff clients.

    This handler:
    - Processes subscribe actions to add topic subscriptions
    - Processes unsubscribe actions to remove topic subscriptions
    - Integrates with ConnectionManager for subscription tracking
    - Handles subscription errors
    """

    def __init__(
        self,
        connection_manager: ConnectionManager,
    ) -> None:
        """Initialize the subscription handler.

        Args:
            connection_manager: Manager for WebSocket connections
        """
        self._connection_manager = connection_manager
        logger.info("SubscriptionHandler initialized")

    async def handle_subscribe(
        self,
        websocket: WebSocket,
        topics: list[str],
    ) -> None:
        """Add subscriptions for a connection.

        Args:
            websocket: The WebSocket connection to subscribe
            topics: List of topic names to subscribe to

        Raises:
            CodebuffSessionError: If session is not found
            CodebuffError: If subscription fails
        """
        session = await self._connection_manager.get_session(websocket)
        if session is None:
            logger.error("Attempted to subscribe unknown session")
            raise CodebuffSessionError(
                "Session not found",
                details={"error": "Connection not registered"},
            )

        logger.info(
            "Handling subscribe: session_id=%s, topics=%s",
            session.session_id,
            ", ".join(topics),
        )

        try:
            # Validate topics
            if not topics:
                logger.warning(
                    "Empty topics list for subscribe: session_id=%s",
                    session.session_id,
                )
                raise CodebuffError(
                    "No topics provided for subscription",
                    details={"session_id": session.session_id},
                )

            # Add subscriptions through connection manager
            await self._connection_manager.subscribe(websocket, topics)

            logger.info(
                "Successfully subscribed session %s to %d topics",
                session.session_id,
                len(topics),
            )

        except CodebuffSessionError:
            # Re-raise session errors
            raise
        except Exception as e:
            logger.error(
                "Error subscribing session %s: %s",
                session.session_id,
                str(e),
                exc_info=True,
            )
            raise CodebuffError(
                f"Failed to subscribe to topics: {e!s}",
                details={
                    "session_id": session.session_id,
                    "topics": topics,
                },
            )

    async def handle_unsubscribe(
        self,
        websocket: WebSocket,
        topics: list[str],
    ) -> None:
        """Remove subscriptions for a connection.

        Args:
            websocket: The WebSocket connection to unsubscribe
            topics: List of topic names to unsubscribe from

        Raises:
            CodebuffSessionError: If session is not found
            CodebuffError: If unsubscription fails
        """
        session = await self._connection_manager.get_session(websocket)
        if session is None:
            logger.error("Attempted to unsubscribe unknown session")
            raise CodebuffSessionError(
                "Session not found",
                details={"error": "Connection not registered"},
            )

        logger.info(
            "Handling unsubscribe: session_id=%s, topics=%s",
            session.session_id,
            ", ".join(topics),
        )

        try:
            # Validate topics
            if not topics:
                logger.warning(
                    "Empty topics list for unsubscribe: session_id=%s",
                    session.session_id,
                )
                raise CodebuffError(
                    "No topics provided for unsubscription",
                    details={"session_id": session.session_id},
                )

            # Remove subscriptions through connection manager
            await self._connection_manager.unsubscribe(websocket, topics)

            logger.info(
                "Successfully unsubscribed session %s from %d topics",
                session.session_id,
                len(topics),
            )

        except CodebuffSessionError:
            # Re-raise session errors
            raise
        except Exception as e:
            logger.error(
                "Error unsubscribing session %s: %s",
                session.session_id,
                str(e),
                exc_info=True,
            )
            raise CodebuffError(
                f"Failed to unsubscribe from topics: {e!s}",
                details={
                    "session_id": session.session_id,
                    "topics": topics,
                },
            )
