"""
Backend request manager implementation.

This module provides the implementation of the backend request manager interface.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.backend_request_manager_interface import IBackendRequestManager
from src.core.interfaces.response_processor_interface import IResponseProcessor
from src.core.services.empty_response_middleware import EmptyResponseRetryError

logger = logging.getLogger(__name__)


class BackendRequestManager(IBackendRequestManager):
    """Implementation of the backend request manager."""

    def __init__(
        self,
        backend_processor: IBackendProcessor,
        response_processor: IResponseProcessor,
        wire_capture: Any | None = None,
    ) -> None:
        """Initialize the backend request manager."""
        self._backend_processor = backend_processor
        self._response_processor = response_processor
        # wire_capture is currently applied at BackendService level to avoid
        # duplicating backend resolution logic; accepted here for future use.

    async def prepare_backend_request(
        self, request_data: ChatRequest, command_result: ProcessedResult
    ) -> ChatRequest | None:
        """Prepare backend request based on command processing results."""
        backend_request: ChatRequest | None = request_data

        if command_result.command_executed and command_result.modified_messages:
            # Check if all modified messages are essentially empty (just whitespace)
            def _message_has_content(message: Any) -> bool:
                role = (
                    message.get("role")
                    if isinstance(message, dict)
                    else getattr(message, "role", None)
                )
                if role != "user":
                    return False
                content = (
                    message.get("content")
                    if isinstance(message, dict)
                    else getattr(message, "content", None)
                )
                if content is None:
                    return False
                # If content is a string, check non-empty after strip
                if isinstance(content, str):
                    return bool(content.strip())
                # If content is a list (multimodal parts), treat non-empty as content
                if isinstance(content, list):
                    return len(content) > 0
                # Fallback for other types: truthiness
                return bool(content)

            has_content = any(
                _message_has_content(m) for m in command_result.modified_messages
            )

            if has_content:
                # Normalize messages to domain ChatMessage instances
                normalized_messages: list[ChatMessage] = []
                for m in command_result.modified_messages:
                    if isinstance(m, ChatMessage):
                        normalized_messages.append(m)
                    elif isinstance(m, dict):
                        normalized_messages.append(ChatMessage(**m))
                    else:
                        # Best-effort conversion
                        normalized_messages.append(
                            ChatMessage(
                                role=getattr(m, "role", "user"),
                                content=getattr(m, "content", ""),
                            )
                        )

                backend_request = ChatRequest(
                    model=request_data.model,
                    messages=normalized_messages,
                    temperature=request_data.temperature,
                    top_p=request_data.top_p,
                    max_tokens=request_data.max_tokens,
                    stream=request_data.stream,
                    extra_body=request_data.extra_body,
                )
            else:
                # All modified messages are empty, skip backend call
                backend_request = None

        return backend_request

    async def process_backend_request(
        self,
        backend_request: ChatRequest,
        session_id: str,
        context: RequestContext,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Process backend request with retry handling."""
        return await self._process_backend_request_with_retry(
            backend_request, session_id, context
        )

    async def _process_backend_request_with_retry(
        self,
        backend_request: ChatRequest,
        session_id: str,
        context: RequestContext,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Process backend request with empty response retry handling."""
        try:
            # First attempt
            backend_response = await self._backend_processor.process_backend_request(
                request=backend_request, session_id=session_id, context=context
            )

            # Process the response through middleware (including empty response detection)
            # Only process non-streaming responses that have content
            if (
                hasattr(backend_response, "content")
                and not backend_request.stream
                and backend_response.content is not None
            ):
                # For non-streaming responses, process through response processor
                try:
                    # Process through response processor for empty response detection
                    # This works for both real implementations and mocks in tests
                    await self._response_processor.process_response(
                        backend_response.content, session_id
                    )
                    # If we get here without exception, response was not empty
                    # Return original response (don't replace with processed content)
                    return backend_response
                except EmptyResponseRetryError as e:
                    logger.info(
                        f"Empty response detected, retrying with recovery prompt: {e.recovery_prompt[:100]}..."
                    )
                    # Create retry request with recovery prompt
                    retry_request = await self._create_retry_request(
                        backend_request, e.recovery_prompt
                    )
                    # Retry the request
                    return await self._backend_processor.process_backend_request(
                        request=retry_request, session_id=session_id, context=context
                    )
            else:
                # For streaming responses or responses without content, return as-is
                # TODO: Implement streaming empty response detection if needed
                return backend_response

        except EmptyResponseRetryError as e:
            # This shouldn't happen here since we catch it above, but just in case
            logger.info(
                f"Empty response detected, retrying with recovery prompt: {e.recovery_prompt[:100]}..."
            )
            retry_request = await self._create_retry_request(
                backend_request, e.recovery_prompt
            )
            return await self._backend_processor.process_backend_request(
                request=retry_request, session_id=session_id, context=context
            )

    async def _create_retry_request(
        self, original_request: ChatRequest, recovery_prompt: str
    ) -> ChatRequest:
        """Create a retry request with the recovery prompt appended."""
        # Copy the original messages
        retry_messages = list(original_request.messages)

        # Add the recovery prompt as a user message
        recovery_message = ChatMessage(role="user", content=recovery_prompt)
        retry_messages.append(recovery_message)

        # Create new request with the recovery prompt
        retry_request = ChatRequest(
            model=original_request.model,
            messages=retry_messages,
            temperature=original_request.temperature,
            top_p=original_request.top_p,
            max_tokens=original_request.max_tokens,
            stream=original_request.stream,
            extra_body=original_request.extra_body,
        )

        return retry_request
