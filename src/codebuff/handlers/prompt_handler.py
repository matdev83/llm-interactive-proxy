"""
Prompt handler for Codebuff LLM requests.

This module handles prompt actions from Codebuff clients, converting them
to OpenAI format, routing to appropriate backends, and streaming responses.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, cast

from src.codebuff.exceptions import CodebuffError
from src.codebuff.format_converter import FormatConverter
from src.codebuff.schemas import PromptAction
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import (
    RequestContext,
    RequestCookies,
    RequestHeaders,
)
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.backend_service import IBackendService

if TYPE_CHECKING:
    from fastapi import WebSocket

    from src.codebuff.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)

# Maximum number of active requests to prevent unbounded memory growth
# This prevents memory leaks when requests complete but aren't cleaned up
_MAX_ACTIVE_REQUESTS = 1000


class PromptHandler:
    """Handles prompt actions (LLM requests) from Codebuff clients.

    This handler:
    - Extracts conversation messages from prompt actions
    - Converts Codebuff format to OpenAI format
    - Routes requests to appropriate backends
    - Streams responses back to clients
    - Handles errors and cancellation
    """

    def __init__(
        self,
        backend_service: IBackendService | None = None,
        format_converter: FormatConverter | None = None,
        connection_manager: ConnectionManager | None = None,
        *,
        # Backwards-compatible names used by legacy Codebuff unit tests
        backend_factory: Any | None = None,
    ) -> None:
        """Initialize the prompt handler.

        This handler historically depended on a "backend factory" that could
        `ensure_backend(...)` and then call `backend.chat_completions(...)`.

        The new architecture routes calls through `IBackendService`.

        For compatibility (and to keep older tests stable), we support both:
        - Preferred: provide `backend_service`
        - Legacy: provide `backend_factory`
        """
        self._backend_service = backend_service
        # Legacy attribute expected by tests
        self._backend_factory = backend_factory

        # Backwards-compatibility: legacy call sites pass (backend_factory, format_converter, connection_manager)
        # positionally. If the first positional argument does not look like an IBackendService,
        # treat it as a backend_factory.
        if (
            self._backend_factory is None
            and self._backend_service is not None
            and not hasattr(self._backend_service, "call_completion")
        ):
            self._backend_factory = self._backend_service
            self._backend_service = None

        if format_converter is None:
            format_converter = FormatConverter()
        if connection_manager is None:
            raise TypeError("connection_manager is required")

        self._format_converter = format_converter
        self._connection_manager = connection_manager
        self._active_requests: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()
        if logger.isEnabledFor(logging.INFO):
            logger.info("PromptHandler initialized")

    async def handle_prompt(
        self,
        websocket: WebSocket,
        action: PromptAction,
    ) -> None:
        def _safe(value: object) -> str:
            """Convert potentially invalid strings to safe UTF-8 for logging."""
            try:
                return (
                    str(value)
                    .encode("utf-8", errors="replace")
                    .decode("utf-8", errors="replace")
                )
            except (TypeError, ValueError, UnicodeError, AttributeError) as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "_safe() conversion failed for value type %s: %s",
                        type(value).__name__,
                        e,
                        exc_info=True,
                    )
                return repr(value)

        """Process a prompt action and stream the response.

        Args:
            websocket: The WebSocket connection to send responses to
            action: The prompt action to process

        Raises:
            CodebuffError: If prompt processing fails
        """
        session = await self._connection_manager.get_session(websocket)
        if session is None:
            logger.error("Attempted to handle prompt for unknown session")
            error_msg = self._format_converter.create_error_response(
                user_input_id=action.promptId,
                error_message="Session not found",
            )
            await websocket.send_json(error_msg.model_dump(by_alias=True))
            return

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Handling prompt: session_id=%s, prompt_id=%s, model=%s",
                _safe(session.session_id),
                _safe(action.promptId),
                _safe(action.model),
            )

        # Store fingerprint ID if provided
        if action.fingerprintId:
            session.fingerprint_id = action.fingerprintId

        # Store auth token if provided
        if action.authToken:
            session.auth_token = action.authToken

        try:
            # Extract messages from the action
            messages = self._extract_messages(action)

            # Convert to OpenAI format
            openai_messages = self._format_converter.codebuff_to_openai(
                messages, action.sessionState
            )

            # Determine the model to use
            model = action.model or "gpt-4"

            # Route to backend and stream response
            # Wrap in task for cancellation support and proper cleanup
            await self._stream_response_with_tracking(
                websocket=websocket,
                prompt_id=action.promptId,
                messages=openai_messages,
                model=model,
                session_state=action.sessionState,
            )

        except Exception as e:
            logger.error(
                "Error handling prompt for session %s: %s",
                session.session_id,
                str(e),
                exc_info=True,
            )
            error_msg = self._format_converter.create_error_response(
                user_input_id=action.promptId,
                error_message=f"Failed to process prompt: {e!s}",
            )
            await websocket.send_json(error_msg.model_dump(by_alias=True))

    def _extract_messages(self, action: PromptAction) -> list[ChatMessage]:
        """Extract conversation messages from a prompt action.

        Args:
            action: The prompt action to extract messages from

        Returns:
            List of ChatMessage objects

        Raises:
            CodebuffError: If message extraction fails
        """
        messages: list[ChatMessage] = []

        # Extract from content field if present
        if action.content:
            messages.extend(action.content)

        # Extract from prompt field if present
        if action.prompt:
            messages.append(ChatMessage(role="user", content=action.prompt))

        # Extract from session state if present
        if action.sessionState:
            session_messages_raw = action.sessionState.get("messages", [])
            if session_messages_raw:
                # Convert raw dicts to ChatMessage if they are not already
                session_messages = [
                    m if isinstance(m, ChatMessage) else ChatMessage(**m)
                    for m in session_messages_raw
                ]
                messages.extend(session_messages)

        if not messages:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("No messages found in prompt action")
            raise CodebuffError(
                "No messages found in prompt action",
                details={"prompt_id": action.promptId},
            )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Extracted %d messages from prompt action %s",
                len(messages),
                action.promptId,
            )
        return messages

    def _determine_backend_type(self, model: str) -> str:
        """Determine backend type based on model name.

        This is a small legacy routing heuristic used by Codebuff.
        """
        model_l = (model or "").lower()
        if model_l.startswith("claude"):
            return "anthropic"
        if model_l.startswith("gemini"):
            return "gemini"
        # Default GPT + unknown models -> OpenAI
        return "openai"

    async def _stream_response_with_tracking(
        self,
        websocket: WebSocket,
        prompt_id: str,
        messages: list[ChatMessage],
        model: str,
        session_state: dict[str, Any],
    ) -> None:
        """Stream LLM response with task tracking for cancellation support.

        This method wraps _stream_response in a task and ensures proper cleanup
        to prevent memory leaks from accumulating completed tasks.

        Args:
            websocket: The WebSocket connection to send responses to
            prompt_id: ID of the prompt being responded to
            messages: OpenAI-formatted messages
            model: Model name to use
            session_state: Current session state

        Raises:
            CodebuffError: If streaming fails
        """

        async def _stream_task() -> None:
            """Wrapper task that ensures cleanup on completion."""
            try:
                await self._stream_response(
                    websocket=websocket,
                    prompt_id=prompt_id,
                    messages=messages,
                    model=model,
                    session_state=session_state,
                )
            finally:
                # Always cleanup on completion (success or failure)
                async with self._lock:
                    self._active_requests.pop(prompt_id, None)
                    # Cleanup completed tasks periodically
                    await self._cleanup_completed_requests_locked()

        # Create and track task
        task = asyncio.create_task(_stream_task())

        async with self._lock:
            # Check if we need to cleanup before adding new task
            if len(self._active_requests) >= _MAX_ACTIVE_REQUESTS:
                await self._cleanup_completed_requests_locked()
                # If still at limit, cancel oldest request
                if len(self._active_requests) >= _MAX_ACTIVE_REQUESTS:
                    oldest_id = next(iter(self._active_requests))
                    oldest_task = self._active_requests.get(oldest_id)
                    if oldest_task:
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                "Max active requests (%d) reached, cancelling oldest request %s",
                                _MAX_ACTIVE_REQUESTS,
                                oldest_id,
                            )
                        oldest_task.cancel()
                        # Don't delete here - let the task's finally block handle cleanup
                        # This ensures consistent cleanup path

            self._active_requests[prompt_id] = task

        try:
            await task
        except asyncio.CancelledError:
            # Task was cancelled - cleanup already handled in finally block
            raise

    async def _stream_response(
        self,
        websocket: WebSocket,
        prompt_id: str,
        messages: list[ChatMessage],
        model: str,
        session_state: dict[str, Any],
    ) -> None:
        """Stream LLM response to the client.

        Args:
            websocket: The WebSocket connection to send responses to
            prompt_id: ID of the prompt being responded to
            messages: OpenAI-formatted ChatMessage objects
            model: Model name to use
            session_state: Current session state

        Raises:
            CodebuffError: If streaming fails
        """
        try:
            # Get session to extract session_id for RequestContext
            session = await self._connection_manager.get_session(websocket)
            if session is None:
                raise CodebuffError(
                    "Session not found for WebSocket connection",
                    details={"prompt_id": prompt_id},
                )

            # messages are already ChatMessage objects
            request = ChatRequest(model=model, messages=messages, stream=True)

            # Create RequestContext with session_id to ensure enforcement boundary is invoked
            context = RequestContext(
                headers=RequestHeaders(),
                cookies=RequestCookies(),
                state=None,
                app_state=None,
                session_id=session.session_id,
            )

            response: Any
            if self._backend_service is not None:
                # Call backend through shared orchestrator (ensures non-forwardable enforcement)
                response = await self._backend_service.call_completion(
                    request=request,
                    stream=True,
                    allow_failover=True,
                    context=context,
                )
            elif self._backend_factory is not None:
                # Legacy path for older Codebuff wiring/tests
                backend_type = self._determine_backend_type(model)
                app_config = getattr(self._backend_factory, "_config", None)
                backend_config = None
                if app_config is not None:
                    backends = getattr(app_config, "backends", None)
                    if isinstance(backends, dict):
                        backend_config = backends.get(backend_type)
                # Type check: _backend_factory may have ensure_backend method (legacy compatibility)
                if hasattr(self._backend_factory, "ensure_backend"):
                    backend = await self._backend_factory.ensure_backend(  # type: ignore[attr-defined]
                        backend_type,
                        app_config,
                        backend_config,
                    )
                else:
                    raise AttributeError("backend_factory does not have ensure_backend method")
                # The legacy backend typically returns a dict-like response or an
                # object with `.response`.
                response = await backend.chat_completions(request.model_dump())
            else:
                raise CodebuffError(
                    "No backend configured for PromptHandler",
                    details={"prompt_id": prompt_id},
                )

            # Handle streaming response
            if isinstance(response, StreamingResponseEnvelope):
                await self._process_streaming_response(
                    websocket=websocket,
                    prompt_id=prompt_id,
                    response=response,
                    session_state=session_state,
                )
            else:
                # Non-streaming response - send as single chunk
                payload: Any
                if hasattr(response, "content"):
                    payload = cast(Any, response).content
                elif hasattr(response, "response"):
                    payload = cast(Any, response).response
                else:
                    payload = response

                content = ""
                if isinstance(payload, dict):
                    content = (
                        payload.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "")
                    )
                if content:
                    chunk_msg = self._format_converter.create_response_chunk(
                        user_input_id=prompt_id,
                        text=content,
                    )
                    await websocket.send_json(chunk_msg.model_dump(by_alias=True))

                # Send final response
                final_msg = self._format_converter.create_prompt_response(
                    prompt_id=prompt_id,
                    session_state=session_state,
                )
                await websocket.send_json(final_msg.model_dump(by_alias=True))

        except Exception as e:
            logger.error(
                "Error streaming response for prompt %s: %s",
                prompt_id,
                str(e),
                exc_info=True,
            )
            raise CodebuffError(
                f"Failed to stream response: {e!s}",
                details={"prompt_id": prompt_id, "model": model},
            )

    async def _process_streaming_response(
        self,
        websocket: WebSocket,
        prompt_id: str,
        response: StreamingResponseEnvelope,
        session_state: dict[str, Any],
    ) -> None:
        """Process a streaming response from the backend.

        Args:
            websocket: The WebSocket connection to send responses to
            prompt_id: ID of the prompt being responded to
            response: The streaming response envelope
            session_state: Current session state
        """
        try:
            stream = response.content
            if stream is None:
                return
            async for chunk in stream:
                # Extract text from chunk
                if isinstance(chunk, dict):
                    # Handle dict chunks
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    text = delta.get("content", "")
                elif hasattr(chunk, "choices"):
                    # Handle object chunks with choices attribute
                    # Note: ProcessedResponse doesn't have choices, but some chunks might
                    try:
                        choices_attr = getattr(chunk, "choices", None)  # type: ignore[attr-defined]
                        if choices_attr:
                            delta = getattr(choices_attr[0], "delta", None) if choices_attr else None  # type: ignore[attr-defined]
                            text = getattr(delta, "content", "") if delta else ""  # type: ignore[attr-defined]
                        else:
                            text = ""
                    except (AttributeError, IndexError, TypeError):
                        text = str(chunk)
                else:
                    # ProcessedResponse or other chunk types
                    if hasattr(chunk, "content"):
                        content = chunk.content  # type: ignore[attr-defined]
                        if isinstance(content, str):
                            text = content
                        elif isinstance(content, bytes):
                            text = content.decode("utf-8", errors="replace")
                        else:
                            text = str(chunk)
                    else:
                        text = str(chunk)

                if text:
                    # Send response chunk
                    chunk_msg = self._format_converter.create_response_chunk(
                        user_input_id=prompt_id,
                        text=text,
                    )
                    await websocket.send_json(chunk_msg.model_dump(by_alias=True))

            # Send final prompt response
            final_msg = self._format_converter.create_prompt_response(
                prompt_id=prompt_id,
                session_state=session_state,
            )
            await websocket.send_json(final_msg.model_dump(by_alias=True))

            if logger.isEnabledFor(logging.INFO):
                logger.info("Completed streaming response for prompt %s", prompt_id)

        except Exception as e:
            logger.error(
                "Error processing streaming response for prompt %s: %s",
                prompt_id,
                str(e),
                exc_info=True,
            )
            # Send error response
            error_msg = self._format_converter.create_error_response(
                user_input_id=prompt_id,
                error_message=f"Streaming error: {e!s}",
            )
            await websocket.send_json(error_msg.model_dump(by_alias=True))

    async def cancel_request(self, prompt_id: str) -> None:
        """Cancel an active streaming request.

        Args:
            prompt_id: ID of the prompt to cancel
        """
        async with self._lock:
            task = self._active_requests.get(prompt_id)
            if task:
                if logger.isEnabledFor(logging.INFO):
                    logger.info("Cancelling request for prompt %s", prompt_id)
                task.cancel()
                # Remove immediately on cancellation
                # The task's finally block will handle cleanup gracefully (no-op if already removed)
                self._active_requests.pop(prompt_id, None)
            else:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning("Attempted to cancel unknown request: %s", prompt_id)

    async def _cleanup_completed_requests_locked(self) -> None:
        """Remove completed tasks from active requests to prevent memory leaks.

        Must be called with lock held.
        """
        completed = [
            prompt_id
            for prompt_id, task in self._active_requests.items()
            if task.done()
        ]

        for prompt_id in completed:
            self._active_requests.pop(prompt_id, None)

        if completed and logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Cleaned up %d completed requests (remaining: %d)",
                len(completed),
                len(self._active_requests),
            )
