"""
Backend request manager implementation.

This module provides the implementation of the backend request manager interface.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.backend_request_manager_interface import IBackendRequestManager
from src.core.interfaces.response_processor_interface import (
    IResponseProcessor,
    ProcessedResponse,
)
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
        if not command_result.command_executed:
            return request_data

        logger.debug(
            "Command executed; modified_messages_count=%s, command_results_count=%s",
            len(command_result.modified_messages or []),
            len(command_result.command_results or []),
        )

        final_messages: list[ChatMessage] = list(request_data.messages)
        messages_were_modified = False

        # Process modified_messages: if they exist and have content, they replace original messages
        if command_result.modified_messages:

            def _message_has_content(message: Any) -> bool:
                # (Implementation remains the same)
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
                if isinstance(content, str):
                    return True
                if isinstance(content, list):
                    return len(content) > 0
                return bool(content)

            if any(_message_has_content(m) for m in command_result.modified_messages):
                normalized_messages: list[ChatMessage] = []
                for m in command_result.modified_messages:
                    if isinstance(m, ChatMessage):
                        normalized_messages.append(m)
                    elif isinstance(m, dict):
                        normalized_messages.append(ChatMessage(**m))
                    else:
                        normalized_messages.append(
                            ChatMessage(
                                role=getattr(m, "role", "user"),
                                content=getattr(m, "content", ""),
                            )
                        )
                final_messages = normalized_messages
                messages_were_modified = True
            else:
                # All modified messages are empty, skip backend call
                return None

        # Process command_results: append tool outputs to the message list
        if command_result.command_results:
            extra_messages = []
            for result in command_result.command_results:
                extracted = self._extract_messages_from_command_result(result)
                if extracted:
                    extra_messages.extend(extracted)

            if extra_messages:
                logger.debug(
                    "Appending %s command result messages to backend request",
                    len(extra_messages),
                )
                final_messages.extend(extra_messages)
                messages_were_modified = True

        # If messages were changed, create a new request object
        if messages_were_modified:
            return request_data.model_copy(update={"messages": final_messages})

        # If no changes, return the original request
        return request_data

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

    @staticmethod
    def _extract_messages_from_command_result(result: Any) -> list[ChatMessage]:
        """Extract chat messages embedded in command results for backend replay."""

        def _coerce_message(candidate: Any) -> ChatMessage | None:
            """Convert a candidate object into a ChatMessage when possible."""
            if isinstance(candidate, ChatMessage):
                return candidate

            if hasattr(candidate, "model_dump") and callable(candidate.model_dump):
                try:
                    dumped = candidate.model_dump()
                    if isinstance(dumped, dict):
                        return ChatMessage(**dumped)
                except Exception:
                    return None

            if isinstance(candidate, dict):
                try:
                    return ChatMessage(**candidate)
                except Exception:
                    return None
            return None

        def _iter_candidates(value: Any) -> Iterable[Any]:
            """Yield potential message representations from arbitrary structures."""
            if value is None:
                return ()

            # Prefer explicit tool message containers if present
            if hasattr(value, "tool_messages"):
                tool_value = value.tool_messages
                if isinstance(tool_value, list | tuple):
                    return tuple(tool_value)
                if tool_value is not None:
                    return (tool_value,)

            if isinstance(value, list | tuple):
                return tuple(value)

            return (value,)

        messages: list[ChatMessage] = []
        for candidate in _iter_candidates(result):
            coerced = _coerce_message(candidate)
            if coerced is not None:
                messages.append(coerced)
        return messages

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
                    # Extract processing context for structured output validation
                    processing_context: dict[str, Any] = {}
                    if hasattr(context, "processing_context"):
                        raw_processing_context = getattr(
                            context, "processing_context", {}
                        )
                        if isinstance(raw_processing_context, dict):
                            processing_context = raw_processing_context
                        else:
                            processing_context = {}

                    # Process through response processor for empty response detection
                    # This works for both real implementations and mocks in tests
                    middleware_context = {
                        "original_request": backend_request,
                        "backend_response": backend_response,
                    }
                    if processing_context:
                        middleware_context.update(processing_context)

                    processed_response = (
                        await self._response_processor.process_response(
                            backend_response.content,
                            session_id,
                            middleware_context,
                        )
                    )

                    # Apply structured output middleware if schema is provided
                    if processing_context and processing_context.get("response_schema"):
                        schema_name = processing_context.get("schema_name", "unnamed")
                        request_id = processing_context.get("request_id", session_id)

                        logger.debug(
                            f"Applying structured output middleware - session_id={session_id}, "
                            f"request_id={request_id}, schema_name={schema_name}"
                        )

                        # Import here to avoid circular imports
                        from src.core.di.services import get_service_provider
                        from src.core.services.structured_output_middleware import (
                            StructuredOutputMiddleware,
                        )

                        # Get services from DI container
                        service_provider = get_service_provider()
                        structured_output_middleware = (
                            service_provider.get_required_service(
                                StructuredOutputMiddleware
                            )
                        )

                        # Apply the middleware
                        try:
                            processed_response = (
                                await structured_output_middleware.process(
                                    response=processed_response,
                                    session_id=session_id,
                                    context=processing_context,
                                    is_streaming=False,
                                )
                            )
                            logger.debug(
                                f"Structured output middleware completed - session_id={session_id}, "
                                f"request_id={request_id}"
                            )
                        except Exception as e:
                            logger.error(
                                f"Structured output middleware failed - session_id={session_id}, "
                                f"request_id={request_id}, error={e}"
                            )
                            raise

                    # If we get here without exception, response was not empty
                    # Return the processed response (may include structured output validation)
                    if hasattr(processed_response, "content"):
                        # Update the backend response with processed content
                        backend_response.content = processed_response.content
                        # Add any metadata from processing
                        if (
                            hasattr(processed_response, "metadata")
                            and processed_response.metadata
                            and hasattr(backend_response, "metadata")
                        ):
                            if (
                                not hasattr(backend_response, "metadata")
                                or backend_response.metadata is None
                            ):
                                backend_response.metadata = {}
                            backend_response.metadata.update(
                                processed_response.metadata
                            )

                    return backend_response
                except EmptyResponseRetryError as e:
                    logger.info(
                        f"Empty response detected, retrying with recovery prompt: {e.recovery_prompt[:100]}..."
                    )
                    # Create retry request with recovery prompt
                    retry_request = await self._create_retry_request(
                        e.original_request, e.recovery_prompt
                    )
                    # Retry the request
                    return await self._backend_processor.process_backend_request(
                        request=retry_request, session_id=session_id, context=context
                    )
            else:
                if backend_request.stream:
                    if isinstance(backend_response, StreamingResponseEnvelope):
                        return await self._process_streaming_response(
                            backend_response, backend_request, session_id, context
                        )
                    else:
                        # This case should ideally not be reached if the logic is correct
                        logger.warning(
                            "Expected a StreamingResponseEnvelope but got a ResponseEnvelope for a streaming request."
                        )
                        return backend_response
                else:
                    return backend_response

        except EmptyResponseRetryError as e:
            logger.info(
                f"Empty response detected, retrying with recovery prompt: {e.recovery_prompt[:100]}..."
            )
            retry_request = await self._create_retry_request(
                e.original_request, e.recovery_prompt
            )
            return await self._backend_processor.process_backend_request(
                request=retry_request, session_id=session_id, context=context
            )

    async def _process_streaming_response(
        self,
        stream_envelope: StreamingResponseEnvelope,
        original_request: ChatRequest,
        session_id: str,
        context: RequestContext,
    ) -> StreamingResponseEnvelope:
        """
        Processes a streaming response, checking for an empty stream and
        triggering a retry with a recovery prompt if necessary.
        """
        is_empty = True
        first_chunk = None

        async def stream_wrapper():
            nonlocal is_empty, first_chunk
            async for chunk in stream_envelope.content:
                if is_empty:
                    is_empty = False
                    first_chunk = chunk
                yield chunk

        # Consume one item to see if the stream is empty
        try:
            # We need to manually iterate to check for the first item
            first_chunk = await stream_wrapper().__anext__()
            is_empty = False
        except StopAsyncIteration:
            # Stream is empty, trigger retry
            logger.info("Empty stream detected, retrying with recovery prompt.")
            recovery_prompt = "The previous response was empty, please try again."
            retry_request = await self._create_retry_request(
                original_request, recovery_prompt
            )
            # The result of a retry could be streaming or not, but the original request was for a stream
            retry_response = await self._backend_processor.process_backend_request(
                request=retry_request, session_id=session_id, context=context
            )
            if isinstance(retry_response, StreamingResponseEnvelope):
                return retry_response
            else:
                # If the retry did not return a stream, we need to adapt it.
                async def single_item_stream():
                    yield ProcessedResponse(content=retry_response.content)

                return StreamingResponseEnvelope(
                    content=single_item_stream(),
                    media_type=stream_envelope.media_type,
                    headers=stream_envelope.headers,
                    cancel_callback=stream_envelope.cancel_callback,
                )

        # If not empty, reconstruct the stream with the first chunk
        async def combined_stream():
            if first_chunk is not None:
                yield first_chunk
            async for chunk in stream_wrapper():
                yield chunk

        return StreamingResponseEnvelope(
            content=combined_stream(),
            media_type=stream_envelope.media_type,
            headers=stream_envelope.headers,
            cancel_callback=stream_envelope.cancel_callback,
        )

    async def _create_retry_request(
        self, original_request: ChatRequest, recovery_prompt: str
    ) -> ChatRequest:
        """Create a retry request with the recovery prompt appended."""
        retry_messages = list(original_request.messages)
        recovery_message = ChatMessage(role="user", content=recovery_prompt)
        retry_messages.append(recovery_message)

        # Preserve tools and other fields while appending the recovery message
        return original_request.model_copy(update={"messages": retry_messages})
