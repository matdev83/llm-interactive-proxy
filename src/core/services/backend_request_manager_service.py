"""
Backend request manager implementation.

This module provides the implementation of the backend request manager interface.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Iterable
from typing import Any, cast

from src.core.common.exceptions import BackendError
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.angel_service_interface import IAngelServiceFactory
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.backend_request_manager_interface import IBackendRequestManager
from src.core.interfaces.loop_detector_interface import ILoopDetector
from src.core.interfaces.response_processor_interface import (
    IResponseProcessor,
    ProcessedResponse,
)
from src.core.services.angel_service import AngelService
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
        angel_service_factory: IAngelServiceFactory,
        wire_capture: Any | None = None,
    ) -> None:
        """Initialize the backend request manager."""
        self._backend_processor = backend_processor
        if angel_service_factory is None:
            raise ValueError("angel_service_factory is required")
        self._response_processor = response_processor
        self._angel_service_factory = angel_service_factory
        # wire_capture is currently applied at BackendService level to avoid
        # duplicating backend resolution logic; accepted here for future use.

    async def prepare_backend_request(
        self, request_data: ChatRequest, command_result: ProcessedResult
    ) -> ChatRequest | None:
        """Prepare backend request based on command processing results."""
        if not command_result.command_executed:
            return request_data

        if logger.isEnabledFor(logging.DEBUG):
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
                if logger.isEnabledFor(logging.DEBUG):
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

                        if logger.isEnabledFor(logging.DEBUG):
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
                            if logger.isEnabledFor(logging.DEBUG):
                                logger.debug(
                                    f"Structured output middleware completed - session_id={session_id}, "
                                    f"request_id={request_id}"
                                )
                        except Exception as e:
                            if logger.isEnabledFor(logging.ERROR):
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

                    if (
                        backend_response.metadata
                        and backend_response.metadata.get("tool_call_swallowed")
                        and not (backend_request.extra_body or {}).get(
                            "_tool_call_reactor_retry"
                        )
                    ):
                        retry_response = await self._retry_after_tool_swallow(
                            backend_request, backend_response, session_id, context
                        )
                        if retry_response is not None:
                            return retry_response

                    return backend_response
                except EmptyResponseRetryError as e:
                    if logger.isEnabledFor(logging.INFO):
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
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                "Expected a StreamingResponseEnvelope but got a ResponseEnvelope for a streaming request."
                            )
                        return backend_response
                else:
                    return backend_response

        except EmptyResponseRetryError as e:
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    f"Empty response detected, retrying with recovery prompt: {e.recovery_prompt[:100]}..."
                )
            retry_request = await self._create_retry_request(
                e.original_request, e.recovery_prompt
            )
            return await self._backend_processor.process_backend_request(
                request=retry_request, session_id=session_id, context=context
            )

    async def _retry_after_tool_swallow(
        self,
        original_request: ChatRequest,
        backend_response: ResponseEnvelope,
        session_id: str,
        context: Any,
        *,
        is_streaming: bool = False,
    ) -> ResponseEnvelope | StreamingResponseEnvelope | None:
        """Attempt to re-run the request after a swallowed tool call."""

        metadata = backend_response.metadata or {}
        steering_message = metadata.get("steering_message")
        if not steering_message:
            return None

        swallowed_calls = metadata.get("swallowed_tool_calls")
        original_content = metadata.get("swallowed_original_content")

        extra_body = dict(original_request.extra_body or {})
        extra_body["_tool_call_reactor_retry"] = True

        summary_parts: list[str] = []
        if isinstance(original_content, str) and original_content.strip():
            summary_parts.append(original_content.strip())

        if isinstance(swallowed_calls, list) and swallowed_calls:
            descriptions: list[str] = []
            for raw_call in swallowed_calls:
                if not isinstance(raw_call, dict):
                    continue
                function_payload = raw_call.get("function")
                name = None
                if isinstance(function_payload, dict):
                    name = function_payload.get("name")
                if not name:
                    name = raw_call.get("type", "function")
                arguments = None
                if isinstance(function_payload, dict):
                    arguments = function_payload.get("arguments")
                arg_summary = ""
                if arguments is not None:
                    try:
                        arg_summary = json.dumps(arguments, ensure_ascii=False)
                    except Exception:
                        arg_summary = str(arguments)
                descriptions.append(f"name={name} arguments={arg_summary}".strip())
            if descriptions:
                summary_parts.append(
                    "Blocked tool call details:\n" + "\n".join(descriptions)
                )

        if not summary_parts:
            summary_parts.append(
                "A previous assistant response attempted a tool call that was blocked by the proxy."
            )

        proxy_prompt = "[Proxy Notice]\n" + "\n\n".join(summary_parts)
        if steering_message:
            proxy_prompt += "\n\n" + str(steering_message)

        system_message = ChatMessage(role="system", content=proxy_prompt)
        new_messages = [*list(original_request.messages), system_message]

        retry_request = original_request.model_copy(
            update={"messages": new_messages, "extra_body": extra_body}
        )

        try:
            retry_response = await self._backend_processor.process_backend_request(
                request=retry_request, session_id=session_id, context=context
            )
        except Exception as exc:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Tool call reactor retry failed for session %s: %s",
                    session_id,
                    exc,
                    exc_info=True,
                )
            fallback_metadata = dict(metadata)
            fallback_metadata["tool_call_reactor_retry_failed"] = True
            return ResponseEnvelope(content="", metadata=fallback_metadata)

        if (
            not is_streaming
            and isinstance(retry_response, ResponseEnvelope)
            and not retry_request.stream
        ):
            try:
                middleware_context = {
                    "original_request": retry_request,
                    "backend_response": retry_response,
                }
                processed_retry = await self._response_processor.process_response(
                    retry_response.content,
                    session_id,
                    middleware_context,
                )
                if hasattr(processed_retry, "content"):
                    retry_response.content = processed_retry.content
                    if (
                        hasattr(processed_retry, "metadata")
                        and processed_retry.metadata
                    ):
                        if retry_response.metadata is None:
                            retry_response.metadata = {}
                        retry_response.metadata.update(processed_retry.metadata)

                if retry_response.metadata is None:
                    retry_response.metadata = {}
                retry_response.metadata["steering_retry_occurred"] = True

                return retry_response
            except Exception as exc:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Processing retry response failed for session %s: %s",
                        session_id,
                        exc,
                        exc_info=True,
                    )
                return backend_response

        if is_streaming:
            if isinstance(retry_response, StreamingResponseEnvelope):
                try:
                    return await self._process_streaming_response(
                        retry_response,
                        retry_request,
                        session_id,
                        context,
                    )
                except Exception as exc:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Failed to process streaming retry for session %s: %s",
                            session_id,
                            exc,
                            exc_info=True,
                        )

            async def _single_chunk_stream() -> AsyncIterator[ProcessedResponse]:
                if isinstance(retry_response, StreamingResponseEnvelope):
                    source_stream = retry_response.content
                else:
                    source_stream = None
                if source_stream is not None:
                    async for item in source_stream:
                        if isinstance(item, ProcessedResponse):
                            yield item
                        else:
                            yield ProcessedResponse(
                                content=getattr(item, "content", item),
                                metadata=getattr(item, "metadata", {}),
                            )
                        return
                yield ProcessedResponse(
                    content=getattr(retry_response, "content", ""),
                    metadata=getattr(retry_response, "metadata", {}),
                )

            # Preserve metadata from retry response if available
            retry_metadata = (
                retry_response.metadata
                if isinstance(retry_response, StreamingResponseEnvelope)
                else None
            )
            return StreamingResponseEnvelope(
                content=_single_chunk_stream(), metadata=retry_metadata
            )

        # Streaming retries are not currently supported; fall back to original response
        return backend_response

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
            if logger.isEnabledFor(logging.WARNING):
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

        angel_model_spec: str | None = None
        angel_frequency: int = 1
        try:
            app_state = getattr(context, "app_state", None)
            if app_state is not None:
                cfg = app_state.get_setting("app_config")
                session_cfg = getattr(cfg, "session", None)
                angel_model_spec = getattr(session_cfg, "angel_model", None)
                angel_frequency = getattr(session_cfg, "angel_frequency", 1)
        except Exception:
            angel_model_spec = None
            angel_frequency = 1

        cancel_callback = stream_envelope.cancel_callback
        loop_detector = self._create_loop_detector()
        original_extra_body = getattr(original_request, "extra_body", None)
        reactor_retry_active = False
        if isinstance(original_extra_body, dict):
            reactor_retry_active = bool(
                original_extra_body.get("_tool_call_reactor_retry")
            )

        async def combined_stream():
            for buffered in prefetched_chunks:
                yield buffered
            if original_stream:
                async for chunk in original_stream:
                    yield chunk

        async def monitored_stream() -> AsyncIterator[ProcessedResponse]:
            swallowed_detected = False

            async for chunk in combined_stream():
                text_fragment = self._extract_text_from_chunk(chunk)
                metadata = (
                    getattr(chunk, "metadata", {}) if hasattr(chunk, "metadata") else {}
                )

                if metadata.get("tool_call_swallowed") and not swallowed_detected:
                    if reactor_retry_active:
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "Tool call swallow detected during retry for session %s; forwarding chunk without additional retry",
                                session_id,
                                chunk,
                            )
                        swallowed_detected = True
                        if isinstance(chunk, ProcessedResponse):
                            yield chunk
                        else:
                            yield ProcessedResponse(
                                content=text_fragment,
                                metadata=metadata,
                            )
                        continue

                    swallowed_detected = True
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(
                            "Detected swallowed tool call during streaming for session %s; retrying with steering context",
                            session_id,
                        )
                    retry_response = await self._retry_after_tool_swallow(
                        original_request,
                        ResponseEnvelope(content=text_fragment, metadata=metadata),
                        session_id,
                        context,
                        is_streaming=True,
                    )
                    if isinstance(retry_response, StreamingResponseEnvelope):
                        if retry_response.content:
                            async for retry_chunk in retry_response.content:
                                yield retry_chunk
                    else:
                        yield ProcessedResponse(
                            content=getattr(retry_response, "content", ""),
                            metadata=getattr(retry_response, "metadata", {}),
                        )
                    return

                if text_fragment:
                    clean_fragment = text_fragment.strip()
                    if clean_fragment.startswith(("data:", "event:")):
                        event = None
                    else:
                        event = loop_detector.process_chunk(text_fragment)
                else:
                    event = None

                if event is not None:
                    if cancel_callback is not None:
                        try:
                            await cancel_callback()
                        except Exception as exc:
                            if logger.isEnabledFor(logging.ERROR):
                                logger.error(
                                    "Failed to invoke streaming cancel callback after loop detection: %s",
                                    exc,
                                    exc_info=True,
                                )

                    # Emit a quiet cancellation marker without leaking debug text
                    cancellation_payload = {
                        "id": f"loop-detector-{int(event.timestamp)}",
                        "object": "chat.completion.chunk",
                        "created": int(event.timestamp),
                        "model": "loop-detector",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": ""},
                                "finish_reason": "cancelled",
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
                            "loop_detected": True,
                        },
                    )
                    # Stop streaming after cancellation to avoid duplicate markers
                    return

                yield chunk  # type: ignore[return-value]

        async def angel_guarded_stream() -> AsyncIterator[ProcessedResponse]:
            # Check if Angel should run before buffering the stream
            should_buffer_for_angel = False
            angel_service_instance = None

            if (
                angel_model_spec
                and isinstance(original_request, ChatRequest)
                and AngelService.should_run_for_request(
                    original_request, angel_frequency
                )
            ):
                try:
                    angel_service_instance = self._angel_service_factory.create(
                        angel_model_spec
                    )
                    if angel_service_instance.is_enabled():
                        should_buffer_for_angel = True
                except Exception:
                    # If we can't create the service, we can't use Angel
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Failed to initialize Angel service for check",
                            exc_info=True,
                        )

            if not should_buffer_for_angel:
                async for chunk in monitored_stream():
                    if isinstance(chunk, ProcessedResponse):
                        yield chunk
                    else:
                        # Normalize raw chunks to ProcessedResponse
                        text_piece = self._extract_text_from_chunk(chunk)
                        yield ProcessedResponse(
                            content=text_piece,
                            metadata=getattr(chunk, "metadata", {}),
                        )
                return

            buffered_chunks: list[ProcessedResponse] = []
            text_fragments: list[str] = []

            async for chunk in monitored_stream():
                if isinstance(chunk, ProcessedResponse):
                    buffered_chunks.append(chunk)
                    text_piece = self._extract_text_from_chunk(chunk)
                else:
                    text_piece = self._extract_text_from_chunk(chunk)
                    buffered_chunks.append(
                        ProcessedResponse(
                            content=text_piece,
                            metadata=getattr(chunk, "metadata", {}),
                        )
                    )

                if text_piece:
                    text_fragments.append(text_piece)

            if not buffered_chunks:
                return

            # We already checked should_buffer_for_angel, so we know we should verify
            # But we need to ensure imports and service availability (already done above)

            try:
                from src.core.di.services import get_service_provider
                from src.core.interfaces.backend_service_interface import (
                    IBackendService,
                )
            except Exception:
                for buffered in buffered_chunks:
                    yield buffered
                return

            combined_text = "".join(text_fragments)
            if not combined_text.strip():
                for buffered in buffered_chunks:
                    yield buffered
                return

            def _extract_text(payload: Any) -> str:
                if payload is None:
                    return ""
                value = getattr(payload, "content", payload)
                if isinstance(value, str):
                    return value
                if isinstance(value, bytes):
                    try:
                        return value.decode("utf-8")
                    except Exception:
                        return value.decode("utf-8", errors="ignore")
                return str(value)

            try:
                provider = get_service_provider()
                backend_service: IBackendService = provider.get_required_service(  # type: ignore[assignment]
                    cast(type, IBackendService)
                )

                # Use the pre-created instance
                if not angel_service_instance:
                    # Should not happen given the check above, but safe fallback
                    angel_service_instance = self._angel_service_factory.create(
                        angel_model_spec or ""
                    )

                verification_request = (
                    angel_service_instance.build_verification_request(
                        original_request, combined_text
                    )
                )

                angel_response = await backend_service.chat_completions(
                    verification_request,
                    stream=False,
                    allow_failover=True,
                    context=None,
                )
                angel_text = _extract_text(angel_response)

                decision = angel_service_instance.parse_angel_output(angel_text)
                steering_msg = (decision.steering_message or "").strip()
                if decision.decision != "steer" or not steering_msg:
                    for buffered in buffered_chunks:
                        yield buffered
                    return

                correction_request = angel_service_instance.build_correction_request(
                    original_request, combined_text, steering_msg
                )

                corrected_response = await backend_service.chat_completions(
                    correction_request,
                    stream=False,
                    allow_failover=True,
                    context=None,
                )
                corrected_text = _extract_text(corrected_response)

                if angel_service_instance.has_override_marker(corrected_text):
                    for buffered in buffered_chunks:
                        yield buffered
                    return

                cleaned = angel_service_instance.strip_override_marker(corrected_text)
                yield ProcessedResponse(
                    content=cleaned,
                    metadata={
                        "corrected_by_angel": True,
                        "is_done": True,
                        "angel_decision": "steer",
                    },
                )
            except Exception:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Angel streaming verification failed; forwarding original chunks",
                        exc_info=True,
                    )
                for buffered in buffered_chunks:
                    yield buffered

        processed_stream: AsyncIterator[ProcessedResponse] = angel_guarded_stream()

        async def _attach_stream_context(
            stream: AsyncIterator[ProcessedResponse | Any],
        ) -> AsyncIterator[ProcessedResponse]:
            async for chunk in stream:
                if isinstance(chunk, ProcessedResponse):
                    processed_metadata = dict(chunk.metadata or {})
                    processed_metadata.setdefault("original_request", original_request)
                    processed_metadata.setdefault("session_id", session_id)
                    chunk.metadata = processed_metadata
                    yield chunk
                    continue

                metadata: dict[str, Any] = {}
                if hasattr(chunk, "metadata"):
                    raw_metadata = chunk.metadata
                    if isinstance(raw_metadata, dict):
                        metadata = dict(raw_metadata)
                metadata.setdefault("original_request", original_request)
                metadata.setdefault("session_id", session_id)
                content_value = getattr(chunk, "content", chunk)
                yield ProcessedResponse(content=content_value, metadata=metadata)

        processed_stream = _attach_stream_context(processed_stream)

        # Route streaming chunks through the response processor so stream processors
        # (tool-call repair, reactor middleware, etc.) run for streaming as well.
        try:
            processed_stream = self._response_processor.process_streaming_response(
                processed_stream, session_id
            )
        except Exception:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Response processor streaming normalization failed; "
                    "returning unprocessed stream",
                    exc_info=True,
                )

        async def _gate_empty_stream(
            stream: AsyncIterator[ProcessedResponse],
        ) -> AsyncIterator[ProcessedResponse]:
            buffered: list[ProcessedResponse] = []
            seen_meaningful = False

            async for chunk in stream:
                meaningful = self._chunk_has_meaningful_output(chunk)
                if not seen_meaningful:
                    if meaningful:
                        seen_meaningful = True
                        if buffered:
                            for buffered_chunk in buffered:
                                yield buffered_chunk
                        yield chunk
                    else:
                        buffered.append(chunk)
                        continue
                else:
                    yield chunk

            if not seen_meaningful:
                raise EmptyResponseRetryError(
                    recovery_prompt=self._STREAM_RECOVERY_PROMPT,
                    session_id=session_id,
                    retry_count=retry_depth + 1,
                    original_request=original_request,
                )

        processed_stream = _gate_empty_stream(processed_stream)

        async def _stream_with_empty_recovery(
            stream: AsyncIterator[ProcessedResponse],
        ) -> AsyncIterator[ProcessedResponse]:
            try:
                async for chunk in stream:
                    yield chunk
            except EmptyResponseRetryError as exc:
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "Empty streaming response detected, retrying with recovery prompt: %s",
                        exc.recovery_prompt[:100],
                    )
                retry_request = await self._create_retry_request(
                    original_request, exc.recovery_prompt
                )
                retry_response = await self._backend_processor.process_backend_request(
                    request=retry_request, session_id=session_id, context=context
                )

                if isinstance(retry_response, StreamingResponseEnvelope):
                    retried = await self._process_streaming_response(
                        retry_response,
                        retry_request,
                        session_id,
                        context,
                        retry_depth=retry_depth + 1,
                    )
                    retry_stream = getattr(retried, "content", None)
                    if retry_stream is not None:
                        async for retry_chunk in retry_stream:
                            yield retry_chunk
                    return

                yield ProcessedResponse(
                    content=getattr(retry_response, "content", ""),
                    metadata=getattr(retry_response, "metadata", {}),
                )
            except Exception as exc:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Streaming middleware failed for session %s: %s",
                        session_id,
                        exc,
                        exc_info=True,
                    )

        processed_stream = _stream_with_empty_recovery(processed_stream)

        return StreamingResponseEnvelope(
            content=processed_stream,
            media_type=stream_envelope.media_type,
            headers=stream_envelope.headers,
            cancel_callback=cancel_callback,
            metadata=stream_envelope.metadata,
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
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "%s Maximum recovery attempts reached for session %s",
                    reason,
                    session_id,
                )
            self._raise_empty_stream_error(
                session_id=session_id,
                reason="empty_stream_retry_failure",
            )

        if logger.isEnabledFor(logging.INFO):
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
            metadata=stream_envelope.metadata,
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
            if logger.isEnabledFor(logging.DEBUG):
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

        # Handle case where chunk is a string
        if isinstance(chunk, str):
            return chunk

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

    @staticmethod
    def _chunk_has_tool_calls(chunk: ProcessedResponse) -> bool:
        """Determine whether a streaming chunk contains tool calls metadata."""
        metadata = getattr(chunk, "metadata", {}) or {}
        if metadata.get("tool_calls"):
            return True

        content = getattr(chunk, "content", None)
        if isinstance(content, dict):
            choices = content.get("choices") or []
            if choices and isinstance(choices[0], dict):
                choice = choices[0]
                message = choice.get("message") or {}
                if isinstance(message, dict) and message.get("tool_calls"):
                    return True
                delta = choice.get("delta") or {}
                if isinstance(delta, dict) and delta.get("tool_calls"):
                    return True
            if content.get("tool_calls"):
                return True
        return False

    def _chunk_has_meaningful_output(self, chunk: ProcessedResponse) -> bool:
        """Check whether a streamed chunk carries user-visible output."""
        metadata = getattr(chunk, "metadata", {}) or {}
        content = getattr(chunk, "content", None)

        # Check for error in metadata (including error dicts and error flag)
        if metadata.get("error"):
            return True

        # Check for finish_reason: "error" which indicates a backend error response
        if metadata.get("finish_reason") == "error":
            return True

        # Check for error in content dict
        if isinstance(content, dict) and content.get("error"):
            return True

        # Check for error in content string (JSON-encoded error response)
        if isinstance(content, str) and '"error"' in content:
            return True

        if metadata.get("tool_call_swallowed") or metadata.get(
            "tool_call_reactor_retry_failed"
        ):
            return True

        if isinstance(content, str):
            if content.strip():
                return True
        elif isinstance(content, bytes | bytearray):
            try:
                decoded = content.decode("utf-8")
            except Exception:
                decoded = content.decode("utf-8", errors="ignore")
            if decoded.strip():
                return True

        # A dict without "choices" is meaningful unless it's just usage/metadata
        if isinstance(content, dict) and content and "choices" not in content:
            # Usage-only chunks (usage, model, id, object, created) are not meaningful
            return not set(content.keys()) <= {
                "usage",
                "model",
                "id",
                "object",
                "created",
            }

        if self._chunk_has_tool_calls(chunk):
            return True

        text = self._extract_text_from_chunk(chunk)
        return bool(text and text.strip())

    def _raise_empty_stream_error(self, session_id: str, reason: str) -> None:
        """Raise a backend error when no content is produced after retries."""
        raise BackendError(
            message="Upstream model returned no content after retries",
            backend_name="gemini-oauth-plan",
            code=reason,
            details={"session_id": session_id},
        )
