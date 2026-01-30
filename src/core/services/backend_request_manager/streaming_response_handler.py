"""
Streaming response handler service.

This service processes streaming backend responses including:
- Response processor middleware wrapping
- Empty-stream recovery with retry prompts
- Loop detection and cancellation
- Tool-call retry coordination
- Angel verification
- Metadata attachment

Requirements: 1.3, 1.4, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 6.1, 6.2, 6.3, 7.1, 7.2, 8.1, 8.2, 9.1, 9.2, 10.1
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, cast

from pydantic.types import JsonValue

from src.core.common.exceptions import (
    BackendError,
    LLMProxyError,
    ParsingError,
    TranslationError,
)
from src.core.domain.backend_request_manager.context_models import (
    ResponseProcessingContext,
    StreamingContext,
)
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.backend_request_manager_components import (
    IAngelStreamVerifier,
    ILoopDetectorFactory,
    IStreamingBackendResponseHandler,
    IToolCallRetryCoordinator,
)
from src.core.interfaces.loop_detector_interface import ILoopDetector
from src.core.interfaces.response_processor_interface import (
    IResponseProcessor,
    ProcessedResponse,
)
from src.core.interfaces.session_cancellation_coordinator_interface import (
    ISessionCancellationCoordinator,
)
from src.core.services.empty_response_middleware import EmptyResponseRetryError
from src.core.transport.session_key_resolver import (
    resolve_session_key_from_request_context,
)

logger = logging.getLogger(__name__)

# Constants matching BackendRequestManager
_STREAM_RECOVERY_PROMPT = "The previous response was empty, please try again."
_MAX_EMPTY_STREAM_RETRIES = 1


@dataclass
class RetryState:
    """Retry state extracted from request."""

    current_retry_count: int
    reactor_retry_active: bool


@dataclass
class AngelConfig:
    """Angel verification configuration extracted from request context."""

    model_spec: str | None
    frequency: int
    max_history: int | None
    eligible_turn_count: int | None
    skip_verification: bool


class BackendStreamingResponseHandler(IStreamingBackendResponseHandler):
    """Service for handling streaming backend responses."""

    def __init__(
        self,
        response_processor: IResponseProcessor,
        loop_detector_factory: ILoopDetectorFactory,
        angel_stream_verifier: IAngelStreamVerifier,
        tool_call_retry_coordinator: IToolCallRetryCoordinator,
        backend_processor: IBackendProcessor,
        cancellation_coordinator: ISessionCancellationCoordinator | None = None,
    ) -> None:
        """Initialize the streaming response handler.

        Args:
            response_processor: Response processor for middleware wrapping
            loop_detector_factory: Factory for creating loop detectors
            angel_stream_verifier: Service for Angel verification
            tool_call_retry_coordinator: Coordinator for tool-call retries
            backend_processor: Backend processor for empty-stream retries
            cancellation_coordinator: Coordinator for session cancellation checks
        """
        self._response_processor = response_processor
        self._loop_detector_factory = loop_detector_factory
        self._angel_stream_verifier = angel_stream_verifier
        self._tool_call_retry_coordinator = tool_call_retry_coordinator
        self._backend_processor = backend_processor
        self._cancellation_coordinator = cancellation_coordinator

    def _extract_text_from_chunk(self, chunk: ProcessedResponse) -> str:
        """Extract textual content from a streaming chunk."""
        content = chunk.content
        if isinstance(content, str):
            return content
        if isinstance(content, bytes):
            try:
                return content.decode("utf-8")
            except UnicodeDecodeError:
                return content.decode("utf-8", errors="ignore")
        if isinstance(content, dict):
            # OPTIMIZATION: Extract from standard OpenAI format directly to avoid expensive json.dumps
            # This is on the hot path for every token (loop detection + meaning check)
            if "choices" in content and isinstance(content["choices"], list):
                choices = content["choices"]
                if choices and isinstance(choices[0], dict):
                    # Try delta (stream) or message (non-stream)
                    delta = choices[0].get("delta") or choices[0].get("message")
                    if isinstance(delta, dict) and "content" in delta:
                        val = delta["content"]
                        if val is not None:
                            return str(val)

            # Fallback: Use dict() to safely handle StopChunkWithUsage which is a dict subclass
            return json.dumps(dict(content))
        return str(content) if content is not None else ""

    def _chunk_has_meaningful_output(self, chunk: ProcessedResponse) -> bool:
        """Check whether a streamed chunk carries user-visible output."""
        metadata = getattr(chunk, "metadata", {}) or {}
        content = getattr(chunk, "content", None)

        # Check for error in metadata
        if metadata.get("error"):
            return True

        accumulated_content = metadata.get("accumulated_content")
        if isinstance(accumulated_content, str) and accumulated_content.strip():
            return True
        accumulated_reasoning = metadata.get("accumulated_reasoning")
        if isinstance(accumulated_reasoning, str) and accumulated_reasoning.strip():
            return True

        # Check for finish_reason in metadata (error/cancelled/terminal cases)
        finish_reason = metadata.get("finish_reason")
        if isinstance(finish_reason, str) and finish_reason in {
            "error",
            "cancelled",
            "security_limit",
            "tool_calls",
        }:
            return True

        # Treat explicit terminal markers as meaningful
        if metadata.get("is_cancellation") is True:
            return True
        if metadata.get("loop_detected") is True:
            return True

        # Check for error in content dict
        if isinstance(content, dict) and content.get("error"):
            return True

        # Check for error in content string
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
            except UnicodeDecodeError:
                decoded = content.decode("utf-8", errors="ignore")
            if decoded.strip():
                return True

        # A dict without "choices" is meaningful unless it's just usage/metadata
        if isinstance(content, dict) and content and "choices" not in content:
            # Usage-only chunks are not meaningful
            return not set(content.keys()) <= {
                "usage",
                "model",
                "id",
                "object",
                "created",
            }

        # Check for tool calls
        if isinstance(content, dict):
            choices = content.get("choices", [])
            if choices and isinstance(choices, list):
                for choice in choices:
                    if isinstance(choice, dict):
                        finish = choice.get("finish_reason")
                        if isinstance(finish, str) and finish in {
                            "error",
                            "cancelled",
                            "security_limit",
                            "tool_calls",
                        }:
                            return True
                        delta = choice.get("delta", {})
                        if delta.get("tool_calls"):
                            return True
                        # PERFORMANCE: Check for content directly to avoid expensive serialization
                        content_val = delta.get("content")
                        if content_val and str(content_val).strip():
                            return True

        text = self._extract_text_from_chunk(chunk)

        return bool(text and text.strip())

    async def _create_retry_request(
        self, original_request: ChatRequest, recovery_prompt: str
    ) -> ChatRequest:
        """Create a retry request with the recovery prompt appended."""
        retry_messages = list(original_request.messages)
        recovery_message = ChatMessage(role="user", content=recovery_prompt)
        retry_messages.append(recovery_message)
        return original_request.model_copy(update={"messages": retry_messages})

    def _raise_empty_stream_error(self, session_id: str, reason: str) -> None:
        """Raise a backend error when no content is produced after retries."""
        raise BackendError(
            message="Upstream model returned no content after retries",
            backend_name=None,
            status_code=204,  # Use 204 No Content to trigger longer dedup window
            details={
                "session_id": session_id,
                "reason": reason,
                "error_type": "empty_stream_after_retries",
            },
        )

    def _extract_retry_state(self, request: ChatRequest) -> RetryState:
        """Extract retry count and active flag from request.

        Returns:
            RetryState with current_retry_count and reactor_retry_active fields.
        """
        extra_body = getattr(request, "extra_body", None)
        current_retry_count = 0
        if isinstance(extra_body, dict):
            current_retry_count = extra_body.get("_tool_call_reactor_retry_count", 0)
            legacy_count = extra_body.get("_dangerous_command_retry_count", 0)
            if isinstance(legacy_count, int) and legacy_count > current_retry_count:
                current_retry_count = legacy_count

        reactor_retry_active = bool(
            isinstance(extra_body, dict) and extra_body.get("_tool_call_reactor_retry")
        )
        return RetryState(
            current_retry_count=current_retry_count,
            reactor_retry_active=reactor_retry_active,
        )

    def _extract_angel_config(self, context: RequestContext) -> AngelConfig:
        """Extract Angel configuration from context.

        Returns:
            AngelConfig containing model_spec and frequency
        """
        # Extract from RequestContext extensions if available
        # This follows the architectural pattern of using typed fields instead of direct app_state access
        angel_model_spec: str | None = None
        angel_frequency: int = 10
        angel_max_history: int | None = None
        eligible_turn_count: int | None = None
        skip_verification = False

        if hasattr(context, "extensions") and context.extensions:
            angel_model_spec_value = context.extensions.get("angel_model", None)
            angel_model_spec = (
                str(angel_model_spec_value)
                if angel_model_spec_value is not None
                else None
            )
            angel_frequency_value = context.extensions.get("angel_frequency", 10)
            # Convert JsonValue to int safely
            if angel_frequency_value is not None:
                if isinstance(angel_frequency_value, int | float):
                    angel_frequency = int(angel_frequency_value)
                elif isinstance(angel_frequency_value, str):
                    try:
                        angel_frequency = int(angel_frequency_value)
                    except (ValueError, TypeError):
                        angel_frequency = 10  # default value
                else:
                    angel_frequency = 10  # default value
            else:
                angel_frequency = 10  # default value

            angel_max_history_value = context.extensions.get("angel_max_history", None)
            if angel_max_history_value is not None:
                if isinstance(angel_max_history_value, int | float):
                    angel_max_history = int(angel_max_history_value)
                elif isinstance(angel_max_history_value, str):
                    try:
                        angel_max_history = int(angel_max_history_value)
                    except (ValueError, TypeError):
                        angel_max_history = None
                else:
                    angel_max_history = None
            else:
                angel_max_history = None

            # Optional per-request eligible turn counter and skip flag
            eligible_turn_value = context.extensions.get(
                "angel_eligible_turn_count", None
            )
            if eligible_turn_value is not None:
                try:
                    if isinstance(eligible_turn_value, int | float | str):
                        eligible_turn_count = int(eligible_turn_value)
                except (TypeError, ValueError):
                    eligible_turn_count = None

            skip_value = context.extensions.get("angel_skip_verification", None)
            if isinstance(skip_value, bool):
                skip_verification = skip_value
            elif isinstance(skip_value, str):
                skip_verification = skip_value.strip().lower() in {
                    "1",
                    "true",
                    "yes",
                    "on",
                }

        return AngelConfig(
            model_spec=angel_model_spec,
            frequency=angel_frequency,
            max_history=angel_max_history,
            eligible_turn_count=eligible_turn_count,
            skip_verification=skip_verification,
        )

    def _wrap_with_middleware(
        self,
        original_stream: AsyncIterator[ProcessedResponse],
        processing_context: ResponseProcessingContext,
        request_context: RequestContext,
    ) -> AsyncIterator[ProcessedResponse]:
        """Wrap stream with response processor middleware with fail-open behavior."""
        backend_name = processing_context.backend_name or ""
        if "gemini" in backend_name.lower():
            return original_stream

        try:
            # Create a new RequestContext with backend and model info from processing_context
            # This matches the non-streaming handler pattern of cloning instead of mutating
            original_request = (
                processing_context.original_request or request_context.original_request
            )
            enriched_context = RequestContext(
                headers=request_context.headers,
                cookies=request_context.cookies,
                state=request_context.state,
                app_state=request_context.app_state,
                client_host=request_context.client_host,
                session_id=processing_context.session_id or request_context.session_id,
                request_id=request_context.request_id,
                agent=request_context.agent,
                original_request=original_request,
                processing_context=request_context.processing_context,
                domain_request=request_context.domain_request,
                raw_body=request_context.raw_body,
                backend=processing_context.backend_name,
                effective_model=processing_context.model_name,
                extensions=request_context.extensions,
                original_domain_request=request_context.original_domain_request,
            )
            return self._response_processor.process_streaming_response(
                original_stream,
                processing_context.session_id,
                enriched_context,
            )
        except (KeyboardInterrupt, SystemExit):
            # Re-raise system exceptions to allow proper cleanup
            raise
        except asyncio.CancelledError:
            # Re-raise cancellation to allow proper cleanup
            raise
        except (
            LLMProxyError,
            ParsingError,
            TranslationError,
            TypeError,
            ValueError,
            AttributeError,
            KeyError,
        ) as e:
            # Catch domain exceptions and common data processing errors for fail-open behavior
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Streaming middleware failed for session %s: %s",
                    processing_context.session_id,
                    e,
                    exc_info=True,
                )
            return original_stream
        except Exception as e:
            # Catch-all for unexpected application-level errors - log with full context but still fail-open
            # System exceptions (KeyboardInterrupt, SystemExit, CancelledError) are excluded above
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Unexpected error in streaming middleware for session %s: %s",
                    processing_context.session_id,
                    e,
                    exc_info=True,
                )
            return original_stream

    def _create_loop_detector(self, session_id: str) -> ILoopDetector | None:
        """Create loop detector with fail-open behavior."""
        try:
            return self._loop_detector_factory.create()
        except Exception as err:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to create loop detector for session %s: %s",
                    session_id,
                    err,
                    exc_info=True,
                )
            return None

    async def _apply_angel_verification(
        self,
        request: ChatRequest,
        processed_stream: AsyncIterator[ProcessedResponse],
        processing_context: ResponseProcessingContext,
        request_context: RequestContext,
        angel_model_spec: str | None,
        angel_frequency: int,
        angel_max_history: int | None,
        angel_eligible_turn_count: int | None,
        angel_skip_verification: bool,
    ) -> AsyncIterator[ProcessedResponse]:
        """Apply Angel verification with fail-open behavior."""
        # Extract stream_id from request_context
        stream_id = processing_context.session_id
        if request_context.request_id is not None:
            stream_id = request_context.request_id
        elif request_context.processing_context is not None:
            processing_values = request_context.processing_context.values
            # ProcessingContext.values is dict[str, Any], no isinstance check needed
            stream_id = (
                processing_values.get("stream_id", processing_context.session_id)
                or processing_context.session_id
            )

        streaming_context: StreamingContext = {
            "session_id": processing_context.session_id,
            "stream_id": stream_id,
            "angel_model_spec": angel_model_spec,
            "angel_frequency": angel_frequency,
            "angel_max_history": angel_max_history,
            "angel_eligible_turn_count": angel_eligible_turn_count,
            "angel_skip_verification": angel_skip_verification,
        }

        try:
            # Use RequestContext directly for cancellation gate

            # verify_or_passthrough is an async generator, returns AsyncIterator directly
            verified_stream = self._angel_stream_verifier.verify_or_passthrough(
                request=request,
                stream=processed_stream,
                context=streaming_context,
                request_context=request_context,
            )
            return verified_stream
        except Exception as err:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Angel verification failed for session %s, using original stream: %s",
                    processing_context.session_id,
                    err,
                    exc_info=True,
                )
            return processed_stream

    async def _handle_tool_call_swallowed_stream(
        self,
        chunk: ProcessedResponse,
        request: ChatRequest,
        context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> AsyncIterator[ProcessedResponse] | None:
        """Handle tool-call swallowed detection and retry coordination.

        Returns:
            AsyncIterator of retried chunks if retry occurred, None otherwise
        """
        metadata = getattr(chunk, "metadata", {}) or {}
        retry_state = self._extract_retry_state(request)

        # Skip retry if marker is present and limit not exceeded (prevents infinite loops)
        if retry_state.reactor_retry_active and retry_state.current_retry_count < 3:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Streaming: Skipping tool-call retry (marker present, count=%d) for session %s",
                    retry_state.current_retry_count,
                    processing_context.session_id,
                )
            return None

        # Check if limit exceeded
        if retry_state.reactor_retry_active and retry_state.current_retry_count >= 3:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Streaming: Tool call retry limit exceeded for session %s",
                    processing_context.session_id,
                    exc_info=True,
                )
            terminal_metadata: dict[str, JsonValue] = {
                "dangerous_command_limit_exceeded": True,
                "dangerous_command_retry_count": retry_state.current_retry_count + 1,
                "tool_call_reactor_retry_count": retry_state.current_retry_count + 1,
                "session_terminated": True,
                "is_done": True,
                "finish_reason": "security_limit",
                "_steering_replacement": True,
                "session_id": processing_context.session_id,
            }

            async def terminal_chunk() -> AsyncIterator[ProcessedResponse]:
                yield ProcessedResponse(
                    content="[Proxy Steering - Session Terminated]\n\n"
                    "This session has been terminated due to repeated attempts "
                    "to perform blocked tool calls.",
                    metadata=terminal_metadata,
                )

            return terminal_chunk()

        # Delegate to coordinator
        try:
            from src.core.domain.backend_request_manager.context_models import (
                ToolCallRetryState,
            )
            from src.core.domain.responses import ResponseEnvelope

            response_envelope = ResponseEnvelope(
                content=chunk.content,
                metadata=metadata,
            )

            tool_call_retry_state = ToolCallRetryState(
                retry_count=retry_state.current_retry_count,
                max_retries=3,
                steering_message=None,
                is_streaming=True,
            )

            retry_result = await self._tool_call_retry_coordinator.handle_streaming(
                request=request,
                response=response_envelope,
                context=context,
                retry_state=tool_call_retry_state,
            )

            if retry_result is not None and retry_result.content is not None:

                async def retry_chunks() -> AsyncIterator[ProcessedResponse]:
                    if retry_result.content is None:
                        return
                    async for retry_chunk in retry_result.content:
                        retry_meta = dict(retry_chunk.metadata or {})
                        retry_meta["_steering_replacement"] = True
                        yield ProcessedResponse(
                            content=retry_chunk.content,
                            metadata=retry_meta,
                            usage=retry_chunk.usage,
                        )

                return retry_chunks()
        except (TypeError, AttributeError, RuntimeError, asyncio.CancelledError) as err:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Tool-call retry coordination failed for session %s: %s",
                    processing_context.session_id,
                    err,
                    exc_info=True,
                )
        return None

    async def handle(  # noqa: C901
        self,
        stream: StreamingResponseEnvelope,
        request: ChatRequest,
        context: RequestContext,
        processing_context: ResponseProcessingContext,
        retry_depth: int = 0,
    ) -> StreamingResponseEnvelope:
        """Return a processed streaming response envelope.

        Args:
            stream: The streaming response envelope
            request: The original backend request
            context: Request context
            processing_context: Typed processing context
            retry_depth: Internal retry depth counter to prevent infinite recursion (default: 0)

        Returns:
            A processed streaming response envelope with middleware applied
        """
        original_stream = stream.content
        if original_stream is None:
            # Empty stream - trigger retry
            if processing_context.session_id:
                self._raise_empty_stream_error(
                    session_id=processing_context.session_id,
                    reason="streaming_response_had_no_content_iterator",
                )
            return stream

        # Use original context to avoid direct access to app_state in service layer
        # Extract Angel config from context if available
        angel_config = self._extract_angel_config(context)
        angel_model_spec = angel_config.model_spec
        angel_frequency = angel_config.frequency
        angel_max_history = angel_config.max_history

        # Wrap stream with response processor middleware
        processed_stream = self._wrap_with_middleware(
            original_stream, processing_context, context
        )

        # Create loop detector
        loop_detector = self._create_loop_detector(processing_context.session_id)

        # Wrap with Angel verification if enabled
        verified_stream = await self._apply_angel_verification(
            request,
            processed_stream,
            processing_context,
            context,
            angel_model_spec,
            angel_frequency,
            angel_max_history,
            angel_config.eligible_turn_count,
            angel_config.skip_verification,
        )

        # Process stream with loop detection, tool-call retry, and empty-stream recovery
        async def monitored_stream() -> AsyncIterator[ProcessedResponse]:
            swallowed_detected = False

            async for chunk in verified_stream:
                # Check for tool-call swallowed
                metadata = getattr(chunk, "metadata", {}) or {}
                if (
                    metadata.get("tool_call_swallowed")
                    and not metadata.get("tool_call_reactor_retry_failed")
                    and not swallowed_detected
                ):
                    swallowed_detected = True
                    # Get retry state from request using the helper method
                    retry_state = self._extract_retry_state(request)

                    # Skip retry if marker is present and limit not exceeded (prevents infinite loops)
                    if (
                        retry_state.reactor_retry_active
                        and retry_state.current_retry_count < 3
                    ):
                        # Retry marker present but below limit - skip retry to prevent loops
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "Streaming: Skipping tool-call retry (marker present, count=%d) for session %s",
                                retry_state.current_retry_count,
                                processing_context.session_id,
                            )
                        # Continue with original chunk (no retry)
                        yield chunk
                        continue

                    # Check if limit exceeded before delegating
                    if (
                        retry_state.reactor_retry_active
                        and retry_state.current_retry_count >= 3
                    ):  # MAX_DANGEROUS_COMMAND_RETRIES
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                "Streaming: Tool call retry limit exceeded for session %s",
                                processing_context.session_id,
                                exc_info=True,
                            )
                        # Yield terminal error chunk
                        terminal_metadata: dict[str, JsonValue] = {
                            "dangerous_command_limit_exceeded": True,
                            "dangerous_command_retry_count": retry_state.current_retry_count
                            + 1,
                            "tool_call_reactor_retry_count": retry_state.current_retry_count
                            + 1,
                            "session_terminated": True,
                            "is_done": True,
                            "finish_reason": "security_limit",
                            "_steering_replacement": True,
                            "session_id": processing_context.session_id,
                        }
                        yield ProcessedResponse(
                            content="[Proxy Steering - Session Terminated]\n\n"
                            "This session has been terminated due to repeated attempts "
                            "to perform blocked tool calls.",
                            metadata=terminal_metadata,
                        )
                        return

                    # Delegate to coordinator (always delegate when tool_call_swallowed detected)
                    try:
                        from src.core.domain.backend_request_manager.context_models import (
                            ToolCallRetryState,
                        )
                        from src.core.domain.responses import ResponseEnvelope

                        # Create a response envelope for coordinator
                        response_envelope = ResponseEnvelope(
                            content=chunk.content,
                            metadata=metadata,
                        )

                        tool_call_retry_state = ToolCallRetryState(
                            retry_count=retry_state.current_retry_count,
                            max_retries=3,
                            steering_message=None,
                            is_streaming=True,
                        )

                        retry_result = (
                            await self._tool_call_retry_coordinator.handle_streaming(
                                request=request,
                                response=response_envelope,
                                context=context,
                                retry_state=tool_call_retry_state,
                            )
                        )

                        if retry_result is not None:
                            # Yield retried stream chunks
                            if retry_result.content is not None:
                                async for retry_chunk in retry_result.content:
                                    # Attach steering replacement marker if present
                                    retry_meta = dict(retry_chunk.metadata or {})
                                    retry_meta["_steering_replacement"] = True
                                    yield ProcessedResponse(
                                        content=retry_chunk.content,
                                        metadata=retry_meta,
                                        usage=retry_chunk.usage,
                                    )
                            return
                    except (TypeError, AttributeError, RuntimeError) as err:
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                "Tool-call retry coordination failed for session %s: %s",
                                processing_context.session_id,
                                err,
                                exc_info=True,
                            )

                # Run loop detection
                if loop_detector is not None:
                    try:
                        text_fragment = self._extract_text_from_chunk(chunk)
                        if text_fragment:
                            clean_fragment = text_fragment.strip()
                            if not clean_fragment.startswith(("data:", "event:")):
                                event = loop_detector.process_chunk(text_fragment)
                                if event is not None:
                                    # Cancel stream
                                    cancel_callback = stream.cancel_callback
                                    if cancel_callback is not None:
                                        try:
                                            if isinstance(cancel_callback, Callable):  # type: ignore[arg-type]
                                                if asyncio.iscoroutinefunction(
                                                    cancel_callback
                                                ):
                                                    await cancel_callback()
                                                else:
                                                    cancel_callback()
                                        except Exception as exc:
                                            if logger.isEnabledFor(logging.ERROR):
                                                logger.error(
                                                    "Failed to invoke cancel callback: %s",
                                                    exc,
                                                    exc_info=True,
                                                )

                                    # Emit cancellation chunk
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
                                        content=cast(Any, cancellation_payload),
                                        metadata={
                                            "is_cancellation": True,
                                            "is_done": True,
                                            "loop_pattern": event.pattern,
                                            "loop_repetitions": event.repetition_count,
                                            "loop_detected": True,
                                            "session_id": processing_context.session_id,
                                        },
                                    )
                                    return
                    except (TypeError, AttributeError, RuntimeError, ValueError) as err:
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                "Loop detection failed for chunk in session %s: %s",
                                processing_context.session_id,
                                err,
                                exc_info=True,
                            )

                yield chunk

        # Attach metadata to chunks
        async def attach_metadata_stream() -> AsyncIterator[ProcessedResponse]:
            original_request_payload: JsonValue | None = None
            try:
                if hasattr(request, "model_dump"):
                    original_request_payload = cast(
                        JsonValue, request.model_dump(mode="json")
                    )
            except (AttributeError, TypeError, ValueError):
                original_request_payload = None

            async for chunk in monitored_stream():
                # monitored_stream() returns AsyncIterator[ProcessedResponse], so chunk is always ProcessedResponse
                # NFR1.3: Preserve copy-on-write behavior - create new instance instead of mutating
                # Start with existing metadata or empty dict
                processed_metadata = dict(chunk.metadata) if chunk.metadata else {}

                if original_request_payload is not None:
                    processed_metadata.setdefault(
                        "original_request", original_request_payload
                    )
                processed_metadata.setdefault(
                    "session_id", processing_context.session_id
                )
                if processing_context.client_os:
                    processed_metadata.setdefault(
                        "client_os", cast(JsonValue, processing_context.client_os)
                    )
                # Create new ProcessedResponse instance with updated metadata (copy-on-write)
                yield ProcessedResponse(
                    content=chunk.content,
                    usage=chunk.usage,
                    metadata=processed_metadata,
                )

        # Gate empty stream
        async def gate_empty_stream() -> AsyncIterator[ProcessedResponse]:
            buffered: list[ProcessedResponse] = []
            seen_meaningful = False

            async for chunk in attach_metadata_stream():
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
                # Use retry_depth + 1 to match middleware's retry_count tracking
                # (retry_count starts at 1 for first retry)
                raise EmptyResponseRetryError(
                    recovery_prompt=_STREAM_RECOVERY_PROMPT,
                    session_id=processing_context.session_id,
                    retry_count=retry_depth + 1,
                    original_request=request,
                )

        # Handle empty stream recovery
        async def stream_with_empty_recovery() -> AsyncIterator[ProcessedResponse]:
            try:
                async for chunk in gate_empty_stream():
                    yield chunk
            except EmptyResponseRetryError as exc:
                # Check retry_count from exception (starts at 1, so > means exceeded)
                if exc.retry_count > _MAX_EMPTY_STREAM_RETRIES:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Maximum empty stream recovery attempts reached for session %s",
                            processing_context.session_id,
                        )
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Empty stream recovery exhausted for session %s (retry=%s)",
                            processing_context.session_id,
                            exc.retry_count,
                            exc_info=True,
                        )
                    self._raise_empty_stream_error(
                        session_id=processing_context.session_id,
                        reason="empty_stream_after_retries",
                    )

                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "Empty streaming response detected, retrying with recovery prompt for session %s",
                        processing_context.session_id,
                    )
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Empty streaming response retry triggered for session %s (retry=%s)",
                        processing_context.session_id,
                        exc.retry_count,
                        exc_info=True,
                    )

                # Cancellation gate: ensure session is not cancelled before empty stream retry
                if self._cancellation_coordinator and context:
                    session_key = resolve_session_key_from_request_context(context)
                    if session_key:
                        self._cancellation_coordinator.ensure_not_cancelled(session_key)

                retry_request = await self._create_retry_request(
                    request, exc.recovery_prompt
                )

                retry_response = await self._backend_processor.process_backend_request(
                    request=retry_request,
                    session_id=processing_context.session_id,
                    context=context,
                )

                if isinstance(retry_response, StreamingResponseEnvelope):
                    # Recursively process retried stream with incremented retry_depth
                    retried = await self.handle(
                        stream=retry_response,
                        request=retry_request,
                        context=context,
                        processing_context=processing_context,
                        retry_depth=retry_depth + 1,
                    )
                    if retried.content is not None:
                        async for retry_chunk in retried.content:
                            yield retry_chunk
                    return

                # Non-streaming retry response (shouldn't happen, but handle gracefully)
                yield ProcessedResponse(
                    content=getattr(retry_response, "content", ""),
                    metadata=getattr(retry_response, "metadata", {}),
                )

        content_stream = stream_with_empty_recovery()

        return StreamingResponseEnvelope(
            content=content_stream,
            media_type=stream.media_type,
            headers=stream.headers,
            cancel_callback=stream.cancel_callback,
            metadata=stream.metadata,
        )
