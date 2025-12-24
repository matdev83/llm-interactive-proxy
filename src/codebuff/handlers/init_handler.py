"""
Init handler for Codebuff session initialization.

This module handles init actions from Codebuff clients, storing file context
and returning initialization responses with usage information.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.codebuff.exceptions import CodebuffError, CodebuffSessionError
from src.codebuff.schemas import InitAction, InitResponseAction

if TYPE_CHECKING:
    from fastapi import WebSocket

    from src.codebuff.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)


class InitHandler:
    """Handles init actions (session initialization) from Codebuff clients.

    This handler:
    - Stores file context in session state
    - Associates fingerprint ID with the session
    - Returns init-response with dummy usage values
    - Handles initialization errors
    """

    def __init__(
        self,
        connection_manager: ConnectionManager,
    ) -> None:
        """Initialize the init handler.

        Args:
            connection_manager: Manager for WebSocket connections
        """
        self._connection_manager = connection_manager
        logger.info("InitHandler initialized")

    async def handle_init(
        self,
        websocket: WebSocket,
        action: InitAction,
    ) -> InitResponseAction:
        """Initialize a session with file context.

        Args:
            websocket: The WebSocket connection to send responses to
            action: The init action to process

        Returns:
            InitResponseAction object to be wrapped by the server

        Raises:
            CodebuffSessionError: If session is not found
            CodebuffError: If initialization fails
        """
        session = await self._connection_manager.get_session(websocket)
        if session is None:
            logger.error("Attempted to handle init for unknown session")
            raise CodebuffSessionError(
                "Session not found",
                details={"error": "Connection not registered"},
            )

        logger.info(
            "Handling init: session_id=%s, fingerprint_id=%s",
            session.session_id,
            action.fingerprintId,
        )

        try:
            # Store fingerprint ID
            session.fingerprint_id = action.fingerprintId

            # Store auth token if provided
            if action.authToken:
                session.auth_token = action.authToken

            # Store file context
            session.file_context = action.fileContext

            logger.info(
                "Stored file context for session %s: %d files",
                session.session_id,
                len(action.fileContext) if action.fileContext else 0,
            )

            # Create init response with dummy usage values
            response = self._create_init_response(
                message="Session initialized successfully",
                usage=0.0,
                remaining_balance=float("inf"),
            )

            logger.info("Session initialized: session_id=%s", session.session_id)
            return response

        except Exception as e:
            logger.error(
                "Error handling init for session %s: %s",
                session.session_id,
                str(e),
                exc_info=True,
            )
            raise CodebuffError(
                f"Failed to initialize session: {e!s}",
                details={
                    "session_id": session.session_id,
                    "fingerprint_id": action.fingerprintId,
                },
            )

    def _create_init_response(
        self,
        message: str,
        usage: float,
        remaining_balance: float,
    ) -> InitResponseAction:
        """Create an init-response action message.

        Args:
            message: Success message
            usage: Usage amount (dummy value for MVP)
            remaining_balance: Remaining balance (dummy value for MVP)

        Returns:
            InitResponseAction object
        """
        return InitResponseAction(
            type="init-response",
            message=message,
            agentNames=None,
            usage=usage,
            remainingBalance=remaining_balance,
            next_quota_reset=None,
        )
