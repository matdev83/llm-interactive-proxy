"""WebSocket client for OpenAI Responses API.

This module provides a WebSocket client for connecting to OpenAI's
WebSocket endpoint at wss://api.openai.com/v1/responses, enabling
low-latency, persistent connections optimized for tool-call-heavy workflows.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator
from typing import Any

import websockets  # type: ignore[import-untyped]
from cachetools import TTLCache
from websockets.exceptions import WebSocketException  # type: ignore[import-untyped]

from src.connectors.contracts import ConnectorRequestContext
from src.core.common.exceptions import (
    AuthenticationError,
    InvalidRequestError,
    ServiceUnavailableError,
)
from src.core.common.wire_boundary_capture import (
    capture_websocket_backend_inbound,
    capture_websocket_backend_outbound,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse

logger = logging.getLogger(__name__)

# WebSocket connection timeout per OpenAI documentation (60 minutes)
WS_CONNECTION_TIMEOUT = 3600

# Reconnection parameters
WS_RECONNECT_MAX_ATTEMPTS = 3
WS_RECONNECT_BACKOFF_BASE = 2.0
WS_RECONNECT_INITIAL_DELAY = 1.0


class OpenAIWebSocketClient:
    """WebSocket client for OpenAI Responses API.

    Manages persistent WebSocket connections to OpenAI's /v1/responses endpoint,
    handling connection lifecycle, event streaming, and connection-local caching
    for optimized multi-turn conversations.
    """

    def __init__(
        self,
        api_key: str,
        api_base: str = "wss://api.openai.com/v1",
        connection_timeout: int = WS_CONNECTION_TIMEOUT,
        *,
        responses_websocket_mode: str = "v1",
    ) -> None:
        """Initialize the WebSocket client.

        Args:
            api_key: OpenAI API key for authentication
            api_base: Base WebSocket URL (default: wss://api.openai.com/v1)
            connection_timeout: Maximum connection duration in seconds (default: 3600)
            responses_websocket_mode: ``v1`` or ``v2`` for ``OpenAI-Beta: responses-websocket-mode=…``
        """
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.connection_timeout = connection_timeout
        self._responses_websocket_mode = (
            responses_websocket_mode
            if responses_websocket_mode in ("v1", "v2")
            else "v1"
        )
        self._connection: Any = None  # WebSocketClientProtocol | None
        self._connection_start_time: float | None = None
        self._last_extra_headers: dict[str, str] | None = None
        # L4: Use bounded TTL cache to prevent memory leaks in long sessions
        self._response_cache: TTLCache[str, Any] = TTLCache(
            maxsize=128, ttl=connection_timeout
        )
        self._lock = asyncio.Lock()

    async def connect(self, extra_headers: dict[str, str] | None = None) -> None:
        """Establish WebSocket connection to OpenAI.

        Raises:
            AuthenticationError: If authentication fails
            ServiceUnavailableError: If connection cannot be established
        """
        normalized_extra = dict(extra_headers) if extra_headers else {}
        if self._connection and not self._connection.closed:
            if normalized_extra == (self._last_extra_headers or {}):
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("WebSocket connection already established")
                return
            await self.disconnect()

        url = f"{self.api_base}/responses"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "OpenAI-Beta": f"responses-websocket-mode={self._responses_websocket_mode}",
        }
        headers.update(normalized_extra)
        self._last_extra_headers = dict(normalized_extra)

        try:
            if logger.isEnabledFor(logging.INFO):
                logger.info("Connecting to OpenAI WebSocket endpoint: %s", url)

            self._connection = await websockets.connect(
                url,
                extra_headers=headers,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=10,
            )
            self._connection_start_time = time.time()
            self._response_cache.clear()

            if logger.isEnabledFor(logging.INFO):
                logger.info("WebSocket connection established successfully")

        except Exception as e:
            # Handle authentication errors (InvalidStatusCode with 401)
            if hasattr(e, "status_code"):
                status_code = e.status_code  # type: ignore[attr-defined]
                if status_code == 401:
                    raise AuthenticationError(
                        message="Invalid API key for WebSocket connection"
                    ) from e
                # Handle other status code errors
                raise ServiceUnavailableError(
                    message=f"WebSocket connection failed with status {status_code}"
                ) from e
            # Handle WebSocket-specific exceptions
            if isinstance(e, WebSocketException):
                raise ServiceUnavailableError(
                    message=f"WebSocket connection error: {e}"
                ) from e
            # Generic connection failure
            raise ServiceUnavailableError(
                message=f"Failed to establish WebSocket connection: {e}"
            ) from e

    async def disconnect(self) -> None:
        """Close the WebSocket connection gracefully."""
        async with self._lock:
            if self._connection and not self._connection.closed:
                try:
                    await self._connection.close()
                    if logger.isEnabledFor(logging.INFO):
                        logger.info("WebSocket connection closed")
                except Exception as e:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Error closing WebSocket connection: %s",
                            e,
                            exc_info=True,
                        )
                finally:
                    self._connection = None
                    self._connection_start_time = None
                    self._last_extra_headers = None
                    self._response_cache.clear()

    def _is_connection_expired(self) -> bool:
        """Check if connection has exceeded timeout limit."""
        if self._connection_start_time is None:
            return False
        elapsed = time.time() - self._connection_start_time
        return elapsed >= self.connection_timeout

    async def _ensure_connection(
        self, extra_headers: dict[str, str] | None = None
    ) -> None:
        """Ensure connection is active, reconnecting if necessary.

        Raises:
            ServiceUnavailableError: If connection cannot be established
        """
        if self._is_connection_expired():
            if logger.isEnabledFor(logging.INFO):
                logger.info("Connection timeout reached, reconnecting...")
            await self.disconnect()

        await self.connect(extra_headers=extra_headers)

    async def send_response_create(
        self,
        payload: dict[str, Any],
        previous_response_id: str | None = None,
        context: ConnectorRequestContext | None = None,
        backend: str = "openai",
        model: str = "unknown",
        key_name: str | None = None,
    ) -> AsyncGenerator[ProcessedResponse, None]:
        """Send a response.create event and stream back events.

        Args:
            payload: Response API request payload
            previous_response_id: Optional previous response ID for continuation

        Yields:
            ProcessedResponse: Streaming response chunks

        Raises:
            InvalidRequestError: If request is invalid
            ServiceUnavailableError: If connection fails
        """
        extra = None
        if context is not None and isinstance(context.extensions, dict):
            candidate = context.extensions.get("codex_ws_extra_headers")
            if isinstance(candidate, dict):
                extra = {str(k): str(v) for k, v in candidate.items() if v is not None}
        await self._ensure_connection(extra_headers=extra)

        # Build response.create event
        event = {
            "type": "response.create",
            **payload,
        }

        # Add previous_response_id if provided and in cache
        if previous_response_id:
            event["previous_response_id"] = previous_response_id
            if previous_response_id in self._response_cache:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Using cached response ID: %s", previous_response_id)
            elif logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "previous_response_id not in local cache; forwarding upstream continuation id anyway"
                )

        # Remove transport-specific fields
        event.pop("stream", None)
        event.pop("background", None)

        try:
            # Send the event
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Sending response.create event: %s", event.get("type"))

            assert self._connection is not None
            outbound_text = json.dumps(event)
            await capture_websocket_backend_outbound(
                payload=outbound_text.encode("utf-8"),
                backend=backend,
                model=model,
                key_name=key_name,
                context=context,
                message_type="text",
            )
            await self._connection.send(outbound_text)

            # Stream response events
            response_id = None
            async for message in self._connection:
                if isinstance(message, bytes):
                    await capture_websocket_backend_inbound(
                        payload=message,
                        backend=backend,
                        model=model,
                        key_name=key_name,
                        context=context,
                        message_type="binary",
                    )
                    message = message.decode("utf-8")
                else:
                    await capture_websocket_backend_inbound(
                        payload=message.encode("utf-8"),
                        backend=backend,
                        model=model,
                        key_name=key_name,
                        context=context,
                        message_type="text",
                    )

                try:
                    event_data = json.loads(message)
                except json.JSONDecodeError as e:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Failed to parse WebSocket message: %s",
                            e,
                            exc_info=True,
                        )
                    continue

                event_data_type = event_data.get("type")

                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Received event type: %s", event_data_type)

                # Handle error events
                if event_data_type == "error":
                    error_info = event_data.get("error", {})
                    error_code = error_info.get("code", "unknown_error")
                    error_message = error_info.get("message", "Unknown WebSocket error")

                    if error_code == "previous_response_not_found":
                        raise InvalidRequestError(
                            message=f"Previous response not found: {error_message}",
                            details={
                                "code": "previous_response_not_found",
                                "message": error_message,
                            },
                        )
                    if error_code == "websocket_connection_limit_reached":
                        raise ServiceUnavailableError(
                            message="WebSocket connection limit reached (60 minutes)"
                        )

                    raise ServiceUnavailableError(
                        message=f"WebSocket error: {error_message}"
                    )

                # Cache response ID for future requests
                if "response" in event_data:
                    response_obj = event_data["response"]
                    if isinstance(response_obj, dict):
                        response_id = response_obj.get("id")
                        if response_id:
                            self._response_cache[response_id] = event_data

                # Convert event to ProcessedResponse
                processed = self._event_to_processed_response(event_data)
                if processed:
                    yield processed

                # Stop on terminal completion (v1 uses response.done; v2 may emit
                # response.completed without response.done on a persistent socket).
                if event_data_type in ("response.done", "response.completed"):
                    break

        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Error during WebSocket streaming: %s",
                    e,
                    exc_info=True,
                )
            raise

    def _event_to_processed_response(
        self, event_data: dict[str, Any]
    ) -> ProcessedResponse | None:
        """Convert WebSocket event to ProcessedResponse.

        Args:
            event_data: WebSocket event data

        Returns:
            ProcessedResponse or None if event should be skipped
        """
        event_type = event_data.get("type")

        # Skip session events
        if event_type in ("session.created", "session.updated"):
            return None

        # Convert response events to streaming format
        if event_type in ("response.content_part.delta", "response.delta"):
            # Extract delta content
            delta = event_data.get("delta", {})
            content = delta.get("content", "")

            if content or delta:
                return ProcessedResponse(
                    content={"type": "content.delta", "delta": delta},
                    metadata={"event_type": event_type},
                )

        # Preserve full Responses-native payloads for tool-call completion events.
        # Downstream Codex translation needs fields like output_index and the exact
        # top-level event type to reconstruct canonical tool-call chunks.
        if event_type == "response.output_item.done":
            return ProcessedResponse(
                content=event_data,
                metadata={"event_type": event_type},
            )

        # Terminal completion: v1 uses response.done; v2 websocket mode may use
        # response.completed with the same response payload shape.
        if event_type in ("response.done", "response.completed"):
            response_obj = event_data.get("response", {})
            return ProcessedResponse(
                content=response_obj,
                metadata={"event_type": event_type, "done": True},
            )

        # Pass through other events
        return ProcessedResponse(
            content=event_data,
            metadata={"event_type": event_type},
        )

    async def __aenter__(self) -> OpenAIWebSocketClient:
        """Context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        await self.disconnect()
