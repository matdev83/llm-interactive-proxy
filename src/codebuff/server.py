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
    ) -> None:
        """Initialize the WebSocket server.

        Args:
            connection_manager: Manager for WebSocket connections and sessions
            message_router: Router for parsing and validating messages
            prompt_handler: Handler for prompt actions
            init_handler: Handler for init actions
            subscription_handler: Handler for subscription actions
        """
        self._connection_manager = connection_manager
        self._message_router = message_router
        self._prompt_handler = prompt_handler
        self._init_handler = init_handler
        self._subscription_handler = subscription_handler
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._shutdown_event = asyncio.Event()

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
        logger.info("WebSocket connection accepted")

        session_id: str | None = None

        try:
            # Wait for identify message
            session_id = await self._wait_for_identify(websocket)

            if session_id is None:
                logger.warning("Connection closed before identify message received")
                return

            # Register the connection
            self._connection_manager.connect(websocket, session_id)
            logger.info("Connection registered: session_id=%s", session_id)

            # Process messages
            await self._process_messages(websocket)

        except WebSocketDisconnect:
            logger.info("WebSocket disconnected: session_id=%s", session_id)

        except CodebuffSessionError as e:
            logger.error(
                "Session error: %s (session_id=%s)", str(e), session_id, exc_info=True
            )
            # Send error and close
            try:
                error_ack = self._message_router.create_ack(
                    txid=None, success=False, error=str(e)
                )
                await self.send_message(websocket, error_ack)
            except Exception:
                pass  # Connection may already be closed

        except Exception as e:
            logger.error(
                "Unexpected error in connection handler: %s (session_id=%s)",
                str(e),
                session_id,
                exc_info=True,
            )

        finally:
            # Clean up connection
            if session_id is not None:
                try:
                    self._connection_manager.disconnect(websocket)
                except Exception as e:
                    logger.error(
                        "Error during disconnect cleanup: %s", str(e), exc_info=True
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
            validated_message, ack = await self._message_router.route_message(
                raw_message
            )

            # Send ack
            await self.send_message(websocket, ack)

            # Check if it's an identify message
            if not ack.success or not isinstance(validated_message, IdentifyMessage):
                logger.warning("First message was not a valid identify message")
                await websocket.close(code=1008, reason="Expected identify message")
                return None

            return validated_message.clientSessionId

        except WebSocketDisconnect:
            return None
        except Exception as e:
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
                validated_message, ack = await self._message_router.route_message(
                    raw_message
                )

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
                logger.error("Error processing message: %s", str(e), exc_info=True)
                # Try to send error ack
                try:
                    error_ack = self._message_router.create_ack(
                        txid=None, success=False, error=f"Internal error: {e!s}"
                    )
                    await self.send_message(websocket, error_ack)
                except Exception:
                    pass  # Connection may be broken

    async def _handle_message(self, websocket: WebSocket, message: Any) -> None:
        """Handle a validated message.

        Args:
            websocket: The WebSocket connection
            message: The validated message object
        """
        if isinstance(message, PingMessage):
            # Update heartbeat
            self._connection_manager.update_last_seen(websocket)
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
            message_dict = message.model_dump(exclude_none=True)
            message_json = json.dumps(message_dict)
            await websocket.send_text(message_json)
            logger.debug("Sent message: type=%s", message.type)

        except Exception as e:
            logger.error("Error sending message: %s", str(e), exc_info=True)
            raise

    async def start_heartbeat_monitor(self) -> None:
        """Start the background heartbeat monitoring task.

        This task periodically checks for stale connections and closes them.
        """
        if self._heartbeat_task is not None:
            logger.warning("Heartbeat monitor already running")
            return

        async def monitor_loop() -> None:
            """Background task that monitors heartbeats."""
            logger.info("Heartbeat monitor started")
            while not self._shutdown_event.is_set():
                try:
                    await asyncio.sleep(30)  # Check every 30 seconds
                    await self._connection_manager.cleanup_stale_connections()
                except asyncio.CancelledError:
                    logger.info("Heartbeat monitor cancelled")
                    break
                except Exception as e:
                    logger.error(
                        "Error in heartbeat monitor: %s", str(e), exc_info=True
                    )

        self._heartbeat_task = asyncio.create_task(monitor_loop())
        logger.info("Heartbeat monitoring task started")

    async def shutdown(self) -> None:
        """Gracefully shutdown the WebSocket server.

        This method:
        - Signals the heartbeat monitor to stop
        - Waits for the heartbeat task to complete
        - Closes all active connections
        """
        logger.info("Shutting down WebSocket server")

        # Signal shutdown
        self._shutdown_event.set()

        # Cancel heartbeat task
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None

        logger.info("WebSocket server shutdown complete")
