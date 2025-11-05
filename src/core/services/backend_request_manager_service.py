"""
Backend request manager implementation.

This module provides the implementation of the backend request manager interface.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterable
from typing import Any, cast

from src.core.common.exceptions import BackendError
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.backend_request_manager_interface import IBackendRequestManager
from src.core.interfaces.loop_detector_interface import ILoopDetector
from src.core.interfaces.response_processor_interface import (
    IResponseProcessor,
    ProcessedResponse,
)
from src.core.services.empty_response_middleware import EmptyResponseRetryError
from src.loop_detection.hybrid_detector import HybridLoopDetector

logger = logging.getLogger(__name__)


class BackendRequestManager(IBackendRequestManager):
    """Implementation of the backend request manager."""

    _STREAM_RECOVERY_PROMPT = "The previous response was empty, please try again."
    _MAX_EMPTY_STREAM_RETRIES = 1

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
                isinstance(backend_response, ResponseEnvelope)
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
                        ):
                            if backend_response.metadata is None:
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
        retry_depth: int = 0,
    ) -> StreamingResponseEnvelope:
        """
        Processes a streaming response, checking for an empty stream and
        triggering a retry with a recovery prompt if necessary.
        """
        if retry_depth > self._MAX_EMPTY_STREAM_RETRIES:
            logger.warning(
                "Maximum empty stream recovery attempts reached for session %s",
                session_id,
            )
            self._raise_empty_stream_error(
                session_id=session_id,
                reason="empty_stream_after_retries",
            )

        original_stream = stream_envelope.content
        if original_stream is None:
            return await self._retry_stream_with_recovery(
                reason="Streaming response had no content iterator.",
                stream_envelope=stream_envelope,
                original_request=original_request,
                session_id=session_id,
                context=context,
                retry_depth=retry_depth,
            )

        prefetched_chunks: list[ProcessedResponse | bytes] = []

        async for chunk in original_stream:
            prefetched_chunks.append(chunk)
            break
        else:
            # Generator produced no data at all
            pass

        if not prefetched_chunks:
            return await self._retry_stream_with_recovery(
                reason="Streaming response yielded no chunks.",
                stream_envelope=stream_envelope,
                original_request=original_request,
                session_id=session_id,
                context=context,
                retry_depth=retry_depth,
            )

        cancel_callback = stream_envelope.cancel_callback
        loop_detector = self._create_loop_detector()

        async def combined_stream():
            for buffered in prefetched_chunks:
                yield buffered
            if original_stream:
                async for chunk in original_stream:
                    yield chunk

        async def monitored_stream() -> AsyncIterator[ProcessedResponse]:
            async for chunk in combined_stream():
                text_fragment = self._extract_text_from_chunk(chunk)
                if text_fragment:
                    event = loop_detector.process_chunk(text_fragment)
                else:
                    event = None

                if event is not None:
                    if cancel_callback is not None:
                        try:
                            await cancel_callback()
                        except Exception as exc:
                            logger.error(
                                "Failed to invoke streaming cancel callback after loop detection: %s",
                                exc,
                                exc_info=True,
                            )

                    cancellation_message = (
                        "[Response cancelled: Loop detected - Pattern "
                        f"'{event.pattern[:30]}...' repeated {event.repetition_count} times]"
                    )
                    cancellation_payload = {
                        "id": f"loop-detector-{int(event.timestamp)}",
                        "object": "chat.completion.chunk",
                        "created": int(event.timestamp),
                        "model": "loop-detector",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": cancellation_message},
                                "finish_reason": "stop",
                            }
                        ],
                    }
                    yield ProcessedResponse(
                        content=cancellation_payload,
                        metadata={
                            "is_cancellation": True,
                            "is_done": True,
                            "loop_pattern": event.pattern,
                            "loop_repetitions": event.repetition_count,
                        },
                    )
                    return

                yield chunk

        return StreamingResponseEnvelope(
            content=monitored_stream(),
            media_type=stream_envelope.media_type,
            headers=stream_envelope.headers,
            cancel_callback=cancel_callback,
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

    async def _retry_stream_with_recovery(
        self,
        reason: str,
        stream_envelope: StreamingResponseEnvelope,
        original_request: ChatRequest,
        session_id: str,
        context: RequestContext,
        retry_depth: int,
    ) -> StreamingResponseEnvelope:
        if retry_depth >= self._MAX_EMPTY_STREAM_RETRIES:
            logger.warning(
                "%s Maximum recovery attempts reached for session %s",
                reason,
                session_id,
            )
            self._raise_empty_stream_error(
                session_id=session_id,
                reason="empty_stream_retry_failure",
            )

        logger.info("%s", reason)
        recovery_prompt = self._STREAM_RECOVERY_PROMPT
        retry_request = await self._create_retry_request(
            original_request, recovery_prompt
        )
        retry_response = await self._backend_processor.process_backend_request(
            request=retry_request, session_id=session_id, context=context
        )

        if isinstance(retry_response, StreamingResponseEnvelope):
            return await self._process_streaming_response(
                retry_response,
                retry_request,
                session_id,
                context,
                retry_depth=retry_depth + 1,
            )

        async def single_item_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(content=retry_response.content)

        return StreamingResponseEnvelope(
            content=single_item_stream(),
            media_type=stream_envelope.media_type,
            headers=stream_envelope.headers,
            cancel_callback=stream_envelope.cancel_callback,
        )

    def _create_loop_detector(self) -> ILoopDetector:
        """Create or resolve a loop detector instance for streaming inspection."""
        try:
            from src.core.di.services import get_or_build_service_provider

            provider = get_or_build_service_provider()
            detector = provider.get_service(cast(type, ILoopDetector))
            if detector is not None:
                detector.reset()
                return detector
        except Exception:
            logger.debug(
                "Falling back to standalone loop detector for streaming responses",
                exc_info=True,
            )
        fallback = HybridLoopDetector()
        fallback.reset()
        return fallback

    @staticmethod
    def _extract_text_from_chunk(chunk: ProcessedResponse | bytes) -> str:
        """Extract textual content from a streaming chunk for loop analysis."""
        import json

        # Handle case where chunk is raw bytes (from streaming)
        if isinstance(chunk, bytes):
            try:
                decoded = chunk.decode("utf-8")
            except UnicodeDecodeError:
                return ""

            for line in decoded.splitlines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:].strip()
                if payload == "[DONE]":
                    continue
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict):
                    choices = data.get("choices")
                    if isinstance(choices, list) and choices:
                        choice = choices[0]
                        if isinstance(choice, dict):
                            delta = choice.get("delta") or {}
                            if isinstance(delta, dict):
                                content = delta.get("content")
                                if isinstance(content, str):
                                    return content
                                if isinstance(content, list):
                                    fragments_bytes: list[str] = []
                                    for part in content:
                                        if isinstance(part, str):
                                            fragments_bytes.append(part)
                                        elif isinstance(part, dict):
                                            text_part = part.get("text")
                                            if isinstance(text_part, str):
                                                fragments_bytes.append(text_part)
                                    if fragments_bytes:
                                        return "".join(fragments_bytes)
                            message = choice.get("message")
                            if isinstance(message, dict):
                                msg_content = message.get("content")
                                if isinstance(msg_content, str):
                                    return msg_content
            return ""

        # Handle case where chunk is a ProcessedResponse object
        if isinstance(chunk, ProcessedResponse):
            data = chunk.content
            if isinstance(data, str):
                return data
            if isinstance(data, dict):
                choices = data.get("choices")
                if isinstance(choices, list) and choices:
                    choice = choices[0]
                    if isinstance(choice, dict):
                        delta = choice.get("delta")
                        if isinstance(delta, dict):
                            content = delta.get("content")
                            if isinstance(content, str):
                                return content
                            if isinstance(content, list):
                                fragments_processed: list[str] = []
                                for part in content:
                                    if isinstance(part, str):
                                        fragments_processed.append(part)
                                    elif isinstance(part, dict):
                                        text_part = part.get("text")
                                        if isinstance(text_part, str):
                                            fragments_processed.append(text_part)
                                if fragments_processed:
                                    return "".join(fragments_processed)
                        message = choice.get("message")
                        if isinstance(message, dict):
                            msg_content = message.get("content")
                            if isinstance(msg_content, str):
                                return msg_content
        return ""

    def _raise_empty_stream_error(self, session_id: str, reason: str) -> None:
        """Raise a backend error when no content is produced after retries."""
        raise BackendError(
            message="Upstream model returned no content after retries",
            backend_name="gemini-oauth-plan",
            code=reason,
            details={"session_id": session_id},
        )
