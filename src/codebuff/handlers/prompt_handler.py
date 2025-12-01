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
from src.core.domain.responses import StreamingResponseEnvelope

if TYPE_CHECKING:
    from fastapi import WebSocket

    from src.codebuff.connection_manager import ConnectionManager
    from src.core.services.backend_factory import BackendFactory

logger = logging.getLogger(__name__)


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
        backend_factory: BackendFactory,
        format_converter: FormatConverter,
        connection_manager: ConnectionManager,
    ) -> None:
        """Initialize the prompt handler.

        Args:
            backend_factory: Factory for creating backend instances
            format_converter: Converter for message formats
            connection_manager: Manager for WebSocket connections
        """
        self._backend_factory = backend_factory
        self._format_converter = format_converter
        self._connection_manager = connection_manager
        self._active_requests: dict[str, asyncio.Task] = {}
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
            except Exception:
                return repr(value)

        """Process a prompt action and stream the response.

        Args:
            websocket: The WebSocket connection to send responses to
            action: The prompt action to process

        Raises:
            CodebuffError: If prompt processing fails
        """
        session = self._connection_manager.get_session(websocket)
        if session is None:
            logger.error("Attempted to handle prompt for unknown session")
            error_msg = self._format_converter.create_error_response(
                user_input_id=action.promptId,
                error_message="Session not found",
            )
            await websocket.send_json(error_msg)
            return

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
            await self._stream_response(
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
            await websocket.send_json(error_msg)

    def _extract_messages(self, action: PromptAction) -> list[dict[str, Any]]:
        """Extract conversation messages from a prompt action.

        Args:
            action: The prompt action to extract messages from

        Returns:
            List of message dictionaries

        Raises:
            CodebuffError: If message extraction fails
        """
        messages: list[dict[str, Any]] = []

        # Extract from content field if present
        if action.content:
            messages.extend(action.content)

        # Extract from prompt field if present
        if action.prompt:
            messages.append({"role": "user", "content": action.prompt})

        # Extract from session state if present
        if action.sessionState:
            session_messages = action.sessionState.get("messages", [])
            if session_messages:
                messages.extend(session_messages)

        if not messages:
            logger.warning("No messages found in prompt action")
            raise CodebuffError(
                "No messages found in prompt action",
                details={"prompt_id": action.promptId},
            )

        logger.debug(
            "Extracted %d messages from prompt action %s",
            len(messages),
            action.promptId,
        )
        return messages

    async def _stream_response(
        self,
        websocket: WebSocket,
        prompt_id: str,
        messages: list[dict[str, Any]],
        model: str,
        session_state: dict[str, Any],
    ) -> None:
        """Stream LLM response to the client.

        Args:
            websocket: The WebSocket connection to send responses to
            prompt_id: ID of the prompt being responded to
            messages: OpenAI-formatted messages
            model: Model name to use
            session_state: Current session state

        Raises:
            CodebuffError: If streaming fails
        """
        try:
            chat_messages = [
                (
                    msg
                    if isinstance(msg, ChatMessage)
                    else ChatMessage(**cast(dict[str, Any], msg))
                )
                for msg in messages
            ]
            request = ChatRequest(model=model, messages=chat_messages, stream=True)

            # Get the backend for this model
            backend = await self._get_backend_for_model(model)

            # Call the backend
            response = await backend.chat_completions(
                request_data=request,
                processed_messages=messages,
                effective_model=model,
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
                content = (
                    response.response.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
                if content:
                    chunk_msg = self._format_converter.create_response_chunk(
                        user_input_id=prompt_id,
                        text=content,
                    )
                    await websocket.send_json(chunk_msg)

                # Send final response
                final_msg = self._format_converter.create_prompt_response(
                    prompt_id=prompt_id,
                    session_state=session_state,
                )
                await websocket.send_json(final_msg)

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
                    # Handle object chunks
                    text = chunk.choices[0].delta.content if chunk.choices else ""
                else:
                    text = str(chunk)

                if text:
                    # Send response chunk
                    chunk_msg = self._format_converter.create_response_chunk(
                        user_input_id=prompt_id,
                        text=text,
                    )
                    await websocket.send_json(chunk_msg)

            # Send final prompt response
            final_msg = self._format_converter.create_prompt_response(
                prompt_id=prompt_id,
                session_state=session_state,
            )
            await websocket.send_json(final_msg)

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
            await websocket.send_json(error_msg)

    async def _get_backend_for_model(self, model: str) -> Any:
        """Get the appropriate backend for a model.

        Args:
            model: The model name

        Returns:
            Backend instance for the model

        Raises:
            CodebuffError: If backend cannot be determined or created
        """
        # Map model names to backend types
        # This is a simplified mapping - in production, this would be more sophisticated
        backend_type = self._determine_backend_type(model)

        logger.debug("Routing model %s to backend %s", model, backend_type)

        try:
            # Get backend configuration from app config

            app_config = self._backend_factory._config
            backend_config = None

            # Try to get backend config from app config
            if hasattr(app_config, "backends") and app_config.backends:
                backend_config = app_config.backends.get(backend_type)

            # Create and initialize backend
            backend = await self._backend_factory.ensure_backend(
                backend_type=backend_type,
                app_config=app_config,
                backend_config=backend_config,
            )

            return backend

        except Exception as e:
            logger.error(
                "Failed to get backend for model %s: %s",
                model,
                str(e),
                exc_info=True,
            )
            raise CodebuffError(
                f"Backend not available for model {model}: {e!s}",
                details={"model": model, "backend_type": backend_type},
            )

    def _determine_backend_type(self, model: str) -> str:
        """Determine the backend type for a model name.

        Args:
            model: The model name

        Returns:
            Backend type string
        """
        model_lower = model.lower()

        # Anthropic models
        if "claude" in model_lower:
            return "anthropic"

        # OpenAI models
        if any(
            prefix in model_lower
            for prefix in ["gpt-", "o1-", "text-", "davinci", "curie", "babbage"]
        ):
            return "openai"

        # Gemini models
        if "gemini" in model_lower:
            return "gemini"

        # Default to OpenAI
        logger.warning(
            "Unknown model %s, defaulting to OpenAI backend",
            model,
        )
        return "openai"

    async def cancel_request(self, prompt_id: str) -> None:
        """Cancel an active streaming request.

        Args:
            prompt_id: ID of the prompt to cancel
        """
        task = self._active_requests.get(prompt_id)
        if task:
            logger.info("Cancelling request for prompt %s", prompt_id)
            task.cancel()
            del self._active_requests[prompt_id]
        else:
            logger.warning("Attempted to cancel unknown request: %s", prompt_id)
