"""
WebSocket server for Codebuff protocol.

This module implements the WebSocket server that handles Codebuff client
connections and routes messages to appropriate handlers.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from fastapi import WebSocket, WebSocketDisconnect

from src.codebuff.connection_manager import ConnectionManager
from src.codebuff.exceptions import CodebuffSessionError
from src.codebuff.handlers.init_handler import InitHandler
from src.codebuff.handlers.prompt_handler import PromptHandler
from src.codebuff.handlers.subscription_handler import SubscriptionHandler
from src.codebuff.message_router import MessageRouter
from src.codebuff.schemas import (
    AckMessage,
    ActionMessage,
    IdentifyMessage,
    InitAction,
    PingMessage,
    PromptAction,
    ServerActionMessage,
    SubscribeMessage,
    UnsubscribeMessage,
)
from src.core.domain.client_termination import (
    ClientEndOfSessionSignal,
    ClientTerminationReason,
)
from src.core.interfaces.client_end_of_session_service_interface import (
    IClientEndOfSessionService,
)
from src.core.interfaces.session_metrics_initializer_interface import (
    ISessionMetricsInitializer,
)
from src.core.transport.session_key_resolver import create_codebuff_session_key

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


class CodebuffWebSocketServer:
    """WebSocket server for Codebuff protocol.

    This class manages the WebSocket endpoint, handles connection lifecycle,
    and coordinates message routing between clients and handlers.
    """

    def __init__(
        self,
        connection_manager: ConnectionManager,
        message_router: MessageRouter,
        prompt_handler: PromptHandler,
        init_handler: InitHandler,
        subscription_handler: SubscriptionHandler,
        config: Any,
        metrics_initializer: ISessionMetricsInitializer | None = None,
        client_eos_service: IClientEndOfSessionService | None = None,
    ) -> None:
        """Initialize the WebSocket server.

        Args:
            connection_manager: Manager for WebSocket connections and sessions
            message_router: Router for parsing and validating messages
            prompt_handler: Handler for prompt actions
            init_handler: Handler for init actions
            subscription_handler: Handler for subscription actions
            config: Codebuff configuration (with max_message_size_bytes)
            metrics_initializer: Optional service for initializing session metrics
            client_eos_service: Optional service for reporting client termination
        """
        self._connection_manager = connection_manager
        self._message_router = message_router
        self._prompt_handler = prompt_handler
        self._init_handler = init_handler
        self._subscription_handler = subscription_handler
        self.config = config
        self._metrics_initializer = metrics_initializer
        self._client_eos_service = client_eos_service
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._shutdown_event = asyncio.Event()

        if logger.isEnabledFor(logging.INFO):
            logger.info("CodebuffWebSocketServer initialized")

    def register_endpoint(self, app: FastAPI) -> None:
        """Register the WebSocket endpoint with the FastAPI app.

        Args:
            app: FastAPI application instance
        """

        @app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket) -> None:
            """WebSocket endpoint handler."""
            await self.handle_connection(websocket)

        @app.on_event("startup")
        async def startup_event() -> None:
            """Handle application startup."""
            await self.start_heartbeat_monitor()

        @app.on_event("shutdown")
        async def shutdown_event() -> None:
            """Handle application shutdown."""
            await self.shutdown()

        if logger.isEnabledFor(logging.INFO):
            logger.info("WebSocket endpoint registered at /ws")

    async def handle_connection(self, websocket: WebSocket) -> None:
        """Handle a WebSocket connection lifecycle.

        This method manages the complete lifecycle of a WebSocket connection:
        - Accept the connection
        - Wait for identify message
        - Process messages
        - Handle disconnection and cleanup

        Args:
            websocket: The WebSocket connection to handle
        """
        await websocket.accept()

        if logger.isEnabledFor(logging.INFO):
            logger.info("WebSocket connection accepted")
        session_id: str | None = None

        try:
            # Wait for identify message
            session_id = await self._wait_for_identify(websocket)
            if session_id is None:

                if logger.isEnabledFor(logging.WARNING):
                    logger.warning("Connection closed before identify message received")
                return

            # Register the connection
            await self._connection_manager.connect(websocket, session_id)

            if logger.isEnabledFor(logging.INFO):
                logger.info("Connection registered: session_id=%s", session_id)
            # Requirement 5.5: Initialize session metrics after identify
            # This ensures metrics exist before any potential termination
            await self._initialize_session_metrics(session_id)

            # Process messages
            await self._process_messages(websocket)
        except WebSocketDisconnect:

            if logger.isEnabledFor(logging.INFO):
                logger.info("WebSocket disconnected: session_id=%s", session_id)
            # Termination reporting happens in finally block to ensure it always runs

        except CodebuffSessionError as e:

            if logger.isEnabledFor(logging.ERROR):

                logger.error(
                    "Session error: %s (session_id=%s)",
                    str(e),
                    session_id,
                    exc_info=True,
                )
            # Send error and close
            try:
                error_ack = self._message_router.create_ack(
                    txid=None, success=False, error=str(e)
                )
                await self.send_message(websocket, error_ack)
            except (WebSocketDisconnect, RuntimeError, ConnectionError) as send_err:

                if logger.isEnabledFor(logging.DEBUG):

                    logger.debug(
                        "Failed to send error acknowledgment (connection likely closed): %s",
                        send_err,
                    )

        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Unexpected error in connection handler: %s (session_id=%s)",
                    str(e),
                    session_id,
                    exc_info=True,
                )

        finally:
            # Clean up connection
            # Always attempt to close websocket if it was accepted, even if session_id is None
            # This prevents resource leaks when exceptions occur before identify completes
            try:
                await websocket.close(code=1000, reason="Connection cleanup")
            except (WebSocketDisconnect, RuntimeError, ConnectionError) as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Websocket already closed during cleanup: %s",
                        str(e),
                        exc_info=True,
                    )

            # Disconnect from connection manager if session was registered
            if session_id is not None:
                try:
                    await self._connection_manager.disconnect(websocket)
                except (TypeError, RuntimeError, OSError) as e:
                    if logger.isEnabledFor(logging.ERROR):
                        logger.error(
                            "Error during disconnect cleanup: %s", str(e), exc_info=True
                        )
                # Defensive: ensure termination is reported even if exception occurred
                # (only if identify completed and we haven't already reported)
                try:
                    await self._report_client_termination(session_id)
                except asyncio.CancelledError:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Client termination reporting cancelled during cleanup: session_id=%s",
                            session_id,
                        )
                except (RuntimeError, OSError, ValueError) as e:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Failed to report client termination during cleanup: %s",
                            str(e),
                            exc_info=True,
                        )

    async def _wait_for_identify(self, websocket: WebSocket) -> str | None:
        """Wait for and process the identify message.

        Args:
            websocket: The WebSocket connection

        Returns:
            The session ID from the identify message, or None if connection closed
        """
        try:
            raw_message = await websocket.receive_text()
            routed = await self._message_router.route_message(raw_message)
            validated_message = routed.validated_message
            ack = routed.ack

            # Send ack

            await self.send_message(websocket, ack)

            # Check if it's an identify message
            if not ack.success or not isinstance(validated_message, IdentifyMessage):
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning("First message was not a valid identify message")
                await websocket.close(code=1008, reason="Expected identify message")
                return None

            return validated_message.clientSessionId

        except WebSocketDisconnect:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "WebSocket disconnected while waiting for identify message"
                )
            return None
        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Error waiting for identify message: %s", str(e), exc_info=True
                )
            return None

    async def _process_messages(self, websocket: WebSocket) -> None:
        """Process incoming messages from a WebSocket connection.

        Args:
            websocket: The WebSocket connection
        """
        while True:
            try:
                raw_message = await websocket.receive_text()

                # Route and validate message
                routed = await self._message_router.route_message(raw_message)
                validated_message = routed.validated_message
                ack = routed.ack

                # Send ack

                await self.send_message(websocket, ack)

                # If validation failed, continue to next message
                if not ack.success or validated_message is None:
                    continue

                # Handle the message based on type
                await self._handle_message(websocket, validated_message)

            except WebSocketDisconnect:
                break
            except Exception as e:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error("Error processing message: %s", str(e), exc_info=True)
                # Try to send error ack
                try:
                    error_ack = self._message_router.create_ack(
                        txid=None, success=False, error=f"Internal error: {e!s}"
                    )
                    await self.send_message(websocket, error_ack)
                except (WebSocketDisconnect, RuntimeError, OSError) as send_err:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Failed to send error acknowledgment: %s", str(send_err)
                        )

    async def _handle_message(self, websocket: WebSocket, message: Any) -> None:
        """Handle a validated message.

        Args:
            websocket: The WebSocket connection
            message: The validated message object
        """
        if isinstance(message, PingMessage):
            # Update heartbeat
            await self._connection_manager.update_last_seen(websocket)

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Ping received, updated last_seen")
        elif isinstance(message, SubscribeMessage):
            # Handle subscription
            await self._subscription_handler.handle_subscribe(websocket, message.topics)

        elif isinstance(message, UnsubscribeMessage):
            # Handle unsubscription
            await self._subscription_handler.handle_unsubscribe(
                websocket, message.topics
            )

        elif isinstance(message, ActionMessage):
            # Handle action messages
            await self._handle_action(websocket, message)
        else:

            if logger.isEnabledFor(logging.WARNING):
                logger.warning("Unhandled message type: %s", type(message).__name__)

    async def _handle_action(
        self, websocket: WebSocket, message: ActionMessage
    ) -> None:
        """Handle an action message.

        Args:
            websocket: The WebSocket connection
            message: The action message
        """
        action_data = message.data

        if isinstance(action_data, PromptAction):
            # Handle prompt action
            await self._prompt_handler.handle_prompt(websocket, action_data)

        elif isinstance(action_data, InitAction):
            # Handle init action
            response = await self._init_handler.handle_init(websocket, action_data)
            # Send init response
            action_message = ServerActionMessage(type="action", data=response)
            await self.send_message(websocket, action_message)

        else:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("Unhandled action type: %s", type(action_data).__name__)

    async def send_message(
        self, websocket: WebSocket, message: AckMessage | ServerActionMessage
    ) -> None:
        """Send a message to a client.

        Args:
            websocket: The WebSocket connection
            message: The message to send (AckMessage or ServerActionMessage)
        """
        try:
            message_dict = message.model_dump(exclude_none=True, by_alias=True)
            message_json = json.dumps(message_dict)
            await websocket.send_text(message_json)

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Sent message: type=%s", message.type)
        except Exception as e:

            if logger.isEnabledFor(logging.ERROR):
                logger.error("Error sending message: %s", str(e), exc_info=True)
            raise

    async def _initialize_session_metrics(self, client_session_id: str) -> None:
        """Initialize session metrics for Codebuff session.

        Requirement 5.5: Ensure session metrics exist before any potential termination.

        Args:
            client_session_id: The client-provided session ID
        """
        if self._metrics_initializer is None:
            return

        try:
            session_key = create_codebuff_session_key(client_session_id)
            await self._metrics_initializer.ensure_session_metrics(
                session_key, observed_at=datetime.now(timezone.utc)
            )
        except Exception as exc:
            # Requirement 3.9: Fail-open behavior - log but don't raise
            # Design.md line 434: Log with high-signal error code/metric for visibility
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to initialize session metrics for Codebuff session %s: %s",
                    client_session_id,
                    exc,
                    exc_info=True,
                    extra={
                        "session_id": client_session_id,
                        "error_code": "SESSION_METRICS_INIT_FAILED",
                    },
                )

    async def _report_client_termination(self, client_session_id: str) -> None:
        """Report client termination for Codebuff WebSocket disconnect.

        Requirement 1.7, 3.2: Report client termination when WebSocket disconnects.

        Args:
            client_session_id: The client-provided session ID
        """
        if self._client_eos_service is None:
            return

        try:
            session_key = create_codebuff_session_key(client_session_id)
            signal = ClientEndOfSessionSignal(
                session_key=session_key,
                observed_at=datetime.now(timezone.utc),
                reason=ClientTerminationReason.CLIENT_DISCONNECTED,
                details=f"Codebuff WebSocket disconnect - session_id={client_session_id}",
            )
            # Shield termination reporting to ensure it executes even if task is cancelled
            await asyncio.shield(
                self._client_eos_service.report_client_termination(signal)
            )
        except Exception as exc:
            # Fail-open: log but don't raise - termination reporting is best-effort
            # Design.md line 445: Log with high-visibility error code
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to report client termination for Codebuff disconnect: %s",
                    exc,
                    exc_info=True,
                    extra={
                        "session_id": client_session_id,
                        "error_code": "CLIENT_TERMINATION_REPORT_FAILED",
                    },
                )

    async def start_heartbeat_monitor(self) -> None:
        """Start the background heartbeat monitoring task.

        This task periodically checks for stale connections and closes them.
        """
        if self._heartbeat_task is not None:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("Heartbeat monitor already running")
            return

        async def monitor_loop() -> None:
            """Background task that monitors heartbeats."""

            if logger.isEnabledFor(logging.INFO):
                logger.info("Heartbeat monitor started")
            while not self._shutdown_event.is_set():
                try:
                    await asyncio.sleep(30)  # Check every 30 seconds
                    await self._connection_manager.cleanup_stale_connections()
                except asyncio.CancelledError:
                    if logger.isEnabledFor(logging.INFO):
                        logger.info("Heartbeat monitor cancelled")
                    break
                except Exception as e:
                    if logger.isEnabledFor(logging.ERROR):
                        logger.error(
                            "Error in heartbeat monitor: %s", str(e), exc_info=True
                        )

        self._heartbeat_task = asyncio.create_task(monitor_loop())

        if logger.isEnabledFor(logging.INFO):
            logger.info("Heartbeat monitoring task started")

    async def shutdown(self) -> None:
        """Gracefully shutdown the WebSocket server.

        This method:
        - Signals the heartbeat monitor to stop
        - Waits for the heartbeat task to complete
        - Closes all active connections
        """

        if logger.isEnabledFor(logging.INFO):
            logger.info("Shutting down WebSocket server")
        # Signal shutdown
        self._shutdown_event.set()

        # Cancel heartbeat task
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None

        if logger.isEnabledFor(logging.INFO):
            logger.info("WebSocket server shutdown complete")
