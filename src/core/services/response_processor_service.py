from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from typing import Any, cast

from src.core.common.exceptions import (
    LoopDetectionError,
    ParsingError,
)
from src.core.domain.chat import StreamingChatResponse
from src.core.domain.request_context import RequestContext
from src.core.domain.streaming_response_processor import (
    IStreamProcessor,
    StreamingContent,
)
from src.core.domain.usage_summary import UsageSummary
from src.core.interfaces.loop_detector_interface import ILoopDetector
from src.core.interfaces.response_parser_interface import IResponseParser
from src.core.interfaces.response_processor_interface import (
    IResponseMiddleware,
    IResponseProcessor,
    ProcessedResponse,
)
from src.core.interfaces.session_cancellation_coordinator_interface import (
    ISessionCancellationCoordinator,
)
from src.core.interfaces.streaming_response_processor_interface import (
    IStreamNormalizer as IProcessingStreamNormalizer,
)
from src.core.memory.capture_middleware import MemoryCaptureMiddleware
from src.core.memory.response_capture_processor import ResponseCaptureProcessor
from src.core.services.response_pipeline import UnifiedResponsePipeline
from src.core.services.streaming.stream_normalizer import StreamNormalizer
from src.core.transport.session_key_resolver import (
    resolve_session_key_from_request_context,
)

logger = logging.getLogger(__name__)

# Maximum number of background tasks to prevent unbounded memory growth
# If tasks are created faster than they complete, this limit prevents memory leaks
# 1,000 tasks is roughly ~50-100 KB of memory (assuming ~50-100 bytes per task reference)
_MAX_BACKGROUND_TASKS = 1_000


class ResponseProcessor(IResponseProcessor):
    """Unified response processor for both streaming and non-streaming responses.

    This processor uses a single code path for all response processing by treating
    non-streaming responses as a special case of streaming (single chunk with is_done=True).

    Architecture:
        Non-streaming: Response -> UnifiedResponsePipeline -> ProcessedResponse
        Streaming: AsyncIterator -> StreamNormalizer -> AsyncIterator[ProcessedResponse]

    Benefits:
        - DRY: All middleware logic lives in one place (streaming processors)
        - Consistent: Same processing guarantees for both modes
        - Maintainable: Changes only need to be made once
    """

    def __init__(
        self,
        response_parser: IResponseParser,
        app_state: Any | None = None,
        loop_detector_factory: Any | None = None,
        stream_normalizer: IProcessingStreamNormalizer | None = None,
        tool_call_repair_processor: IStreamProcessor | None = None,
        loop_detection_processor: IStreamProcessor | None = None,
        content_accumulation_processor: IStreamProcessor | None = None,
        middleware_application_processor: IStreamProcessor | None = None,
        middleware_list: list[IResponseMiddleware] | None = None,
        memory_capture: MemoryCaptureMiddleware | None = None,
        cancellation_coordinator: ISessionCancellationCoordinator | None = None,
    ) -> None:
        self._app_state = app_state
        self._background_tasks: list[asyncio.Task[Any]] = []
        self._loop_detector_factory = loop_detector_factory
        self._response_parser = response_parser
        self._middleware_list = middleware_list or []
        self._memory_capture = memory_capture
        self._cancellation_coordinator = cancellation_coordinator

        # Angel feature wiring
        self._angel_service: Any | None = None
        self._angel_frequency: int = 1

        # Stream normalizer is typically provided via DI.
        # For testability and graceful degradation, if it is not provided but
        # specialized streaming processors/middleware are supplied, construct a
        # default StreamNormalizer locally.
        if stream_normalizer is None and any(
            x is not None
            for x in (
                tool_call_repair_processor,
                loop_detection_processor,
                content_accumulation_processor,
                middleware_application_processor,
            )
        ):
            from src.core.services.streaming.content_accumulation_processor import (
                ContentAccumulationProcessor,
            )
            from src.core.services.streaming.stream_context_registry import (
                StreamingContextRegistry,
            )

            processors: list[IStreamProcessor] = []
            if tool_call_repair_processor is not None:
                processors.append(tool_call_repair_processor)
            if loop_detection_processor is not None:
                processors.append(loop_detection_processor)

            # Ensure content accumulation is always present for unified pipeline semantics.
            if content_accumulation_processor is not None:
                processors.append(content_accumulation_processor)
            else:
                processors.append(
                    ContentAccumulationProcessor(
                        max_buffer_bytes=10 * 1024 * 1024,
                        registry=StreamingContextRegistry(),
                    )
                )

            if middleware_application_processor is not None:
                processors.append(middleware_application_processor)

            stream_normalizer = StreamNormalizer(processors)

        self._stream_normalizer = stream_normalizer

        # Inject memory response capture middleware into stream normalizer if enabled
        # We need to add it to the END of the chain to capture final processed content
        if (
            self._memory_capture
            and self._stream_normalizer
            and isinstance(self._stream_normalizer, StreamNormalizer)
        ):
            # We can't easily append to _processors as it's private and frozen in StreamNormalizer
            # But we can rely on the fact that we're likely constructing it here or passing it in.
            # However, since we need session_id for capture which is only available at request time,
            # we need a factory or per-request injection mechanism.
            #
            # The current architecture makes this tricky: processors are instantiated once.
            # But ResponseCaptureProcessor needs session_id.
            #
            # Solution: We'll modify process_streaming_response to wrap the iterator with a capture step
            # or rely on UnifiedResponsePipeline modifications.
            #
            # Actually, let's inject it into process_streaming_response logic below instead of here.
            pass

        if self._stream_normalizer is None:
            raise RuntimeError(
                "ResponseProcessor requires an IProcessingStreamNormalizer; "
                "ensure the streaming pipeline is registered."
            )

        # Create unified pipeline for both streaming and non-streaming
        self._unified_pipeline = UnifiedResponsePipeline(self._stream_normalizer)

    async def _apply_angel_verification(
        self, original_request: Any, content: Any, context: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Apply Angel verification and optionally correction.

        Returns a dict with keys:
        - action: "pass" | "steer"
        - corrected_content: str (when action=="steer")
        """
        try:
            from src.core.di.services import get_service_provider
            from src.core.domain.chat import ChatRequest
            from src.core.interfaces.backend_service_interface import IBackendService
            from src.core.services.angel_service import AngelService

            if not self._angel_service:
                # Resolve angel model spec from app_state config
                model_spec = None
                frequency_value: int | None = 1
                try:
                    cfg = (
                        self._app_state.get_setting("app_config")
                        if self._app_state
                        else None
                    )
                    session_cfg = getattr(cfg, "session", None)
                    model_spec = getattr(session_cfg, "angel_model", None)
                    frequency_value = getattr(session_cfg, "angel_frequency", 1)
                except (AttributeError, TypeError, KeyError):
                    model_spec = None
                    frequency_value = 1
                angel_svc = AngelService(model_spec or "")


                if not angel_svc.is_enabled():
                    return {"action": "pass"}
                self._angel_service = angel_svc
                try:
                    freq_int = (
                        int(frequency_value) if frequency_value is not None else 1
                    )
                except (TypeError, ValueError):
                    freq_int = 1
                self._angel_frequency = freq_int if freq_int > 0 else 1

            svc: AngelService = self._angel_service

            if not isinstance(original_request, ChatRequest):
                return {"action": "pass"}

            frequency = getattr(self, "_angel_frequency", 1)
            if not AngelService.should_run_for_request(original_request, frequency):
                return {"action": "pass"}

            verification_request = svc.build_verification_request(
                original_request, content
            )

            # Resolve RequestContext from context dict for cancellation gate
            request_context: RequestContext | None = None
            if context:
                request_context = context.get("request_context")
                if not isinstance(request_context, RequestContext):


                    request_context = None

            # Cancellation gate: ensure session is not cancelled before Angel verification backend call
            if self._cancellation_coordinator and request_context:
                session_key = resolve_session_key_from_request_context(request_context)
                if session_key:
                    self._cancellation_coordinator.ensure_not_cancelled(session_key)

            provider = get_service_provider()
            backend_service: IBackendService = provider.get_required_service(
                cast(type, IBackendService)
            )

            def _extract_text(payload: Any) -> str:
                if payload is None:
                    return ""
                value = getattr(payload, "content", payload)
                if isinstance(value, str):
                    return value
                if isinstance(value, bytes):
                    try:
                        return value.decode("utf-8")
                    except UnicodeDecodeError:
                        return value.decode("utf-8", errors="ignore")
                return str(value)



            angel_response = await backend_service.chat_completions(
                verification_request,
                stream=False,
                allow_failover=True,
                context=request_context,
            )
            angel_text = _extract_text(angel_response)

            decision = svc.parse_angel_output(angel_text)
            if decision.decision == "pass":
                return {"action": "pass"}

            steering_msg = (decision.steering_message or "").strip()
            if not steering_msg:
                return {"action": "pass"}

            correction_request = svc.build_correction_request(
                original_request, content, steering_msg
            )

            # Cancellation gate: ensure session is not cancelled before Angel correction backend call
            if self._cancellation_coordinator and request_context:
                session_key = resolve_session_key_from_request_context(request_context)
                if session_key:
                    self._cancellation_coordinator.ensure_not_cancelled(session_key)

            corrected_response = await backend_service.chat_completions(
                correction_request,
                stream=False,
                allow_failover=True,
                context=request_context,
            )
            corrected_text = _extract_text(corrected_response)

            if svc.has_override_marker(corrected_text):
                return {"action": "pass"}

            cleaned = svc.strip_override_marker(corrected_text)
            return {"action": "steer", "corrected_content": cleaned}
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Angel verification internal error: %s",
                    e,
                    exc_info=True,
                )
            return None

    def add_background_task(self, task: asyncio.Task[Any]) -> None:
        """Add a background task to be managed by the processor.

        Completed tasks are automatically removed to prevent memory leaks.
        """
        # Clean up completed tasks before adding new one (lazy cleanup)
        self._cleanup_completed_tasks()

        # Add task and register callback to remove it when done
        self._background_tasks.append(task)
        task.add_done_callback(self._remove_completed_task)

    def _remove_completed_task(self, task: asyncio.Task[Any]) -> None:
        """Remove a completed task from the background tasks list.

        This callback is registered on each task to prevent memory leaks.
        """
        with contextlib.suppress(ValueError):
            # Task already removed (shouldn't happen, but safe to ignore)
            self._background_tasks.remove(task)

    def _cleanup_completed_tasks(self) -> None:
        """Remove all completed tasks from the background tasks list.

        This prevents unbounded memory growth from accumulating completed tasks.
        """
        # Remove completed tasks in reverse order to avoid index shifting issues
        for i in range(len(self._background_tasks) - 1, -1, -1):
            if self._background_tasks[i].done():
                self._background_tasks.pop(i)

        # Enforce max limit to prevent unbounded growth
        # If we're at the limit, cancel oldest tasks (FIFO eviction)
        if len(self._background_tasks) >= _MAX_BACKGROUND_TASKS:
            excess_count = len(self._background_tasks) - _MAX_BACKGROUND_TASKS + 1
            for i in range(excess_count):
                if i < len(self._background_tasks):
                    task = self._background_tasks[i]
                    if not task.done():
                        task.cancel()
                    self._background_tasks.pop(i)
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Evicted %d oldest background tasks (max=%d reached)",
                    excess_count,
                    _MAX_BACKGROUND_TASKS,
                )

    async def register_middleware(
        self, middleware: IResponseMiddleware, priority: int = 0
    ) -> None:
        """Register a middleware component to process responses."""
        # This method is required by the IResponseProcessor interface
        # but for the new architecture, middleware is handled by the stream processors

    async def process_response(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any] | None = None,
    ) -> ProcessedResponse:
        """Process a non-streaming response through the unified pipeline.

        This method wraps the response as a single-chunk stream, processes it
        through the same middleware chain as streaming responses, then unwraps
        the result back to a single ProcessedResponse.

        Args:
            response: The response object from the backend.
            session_id: The ID of the current session.
            context: Optional context dictionary with additional metadata.

        Returns:
            A ProcessedResponse object.

        Raises:
            LoopDetectionError: If a loop is detected in the response.
            ParsingError: If there is an error parsing the response.
        """
        try:
            # Parse the raw response using the injected parser
            parsed_data = self._response_parser.parse_response(response)
            content = self._response_parser.extract_content(parsed_data)
            usage_dict = self._response_parser.extract_usage(parsed_data)
            usage = UsageSummary.from_dict(usage_dict) if usage_dict else None
            metadata = self._response_parser.extract_metadata(parsed_data) or {}

            # Build initial ProcessedResponse for pipeline
            initial_response = ProcessedResponse(
                content=content,
                usage=usage,
                metadata=metadata,
            )

            # Prepare context metadata for the pipeline
            pipeline_metadata: dict[str, Any] = {
                "original_response": parsed_data,
                **(context or {}),
            }

            # Process through unified pipeline (wraps as single-chunk stream)
            processed_response = await self._unified_pipeline.process_non_streaming(
                initial_response,
                session_id,
                metadata=pipeline_metadata,
            )

            # Check for loop detection in pipeline output
            if processed_response.metadata.get("loop_detected"):
                raise LoopDetectionError(
                    message=f"Loop detected: {processed_response.metadata.get('pattern', 'unknown')}",
                    details={
                        "pattern": processed_response.metadata.get("pattern"),
                        "repetitions": processed_response.metadata.get(
                            "repetition_count"
                        ),
                        "session_id": session_id,
                    },
                )

            # Angel verification for non-streaming responses (post-pipeline)
            try:
                original_request = None
                if context:
                    original_request = context.get("original_request")
                # Only run when angel is configured in session


                if original_request is not None:
                    decision = await self._apply_angel_verification(
                        original_request, processed_response.content or "", context
                    )
                    if decision and decision.get("action") == "steer":
                        corrected = decision.get("corrected_content", "")
                        processed_response = ProcessedResponse(
                            content=corrected,
                            usage=processed_response.usage,
                            metadata=processed_response.metadata,
                        )
            except (KeyError, TypeError, ValueError, AttributeError):
                # Be conservative: do not break normal flow on Angel errors
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning("Angel verification failed; continuing", exc_info=True)

            return processed_response

        except LoopDetectionError:
            # Propagate loop detection as-is
            raise
        except json.JSONDecodeError as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"JSON decoding error in non-streaming response: {e}", exc_info=True
                )
            raise ParsingError(
                message=f"Failed to decode JSON in response: {e}",
                details={"session_id": session_id, "original_error": str(e)},
            ) from e
        except (TypeError, ValueError, AttributeError, KeyError, IndexError) as e:
            # Catch common expected exceptions for data processing
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"Data processing error in non-streaming response: {e}",
                    exc_info=True,
                )
            raise ParsingError(
                message=f"Error processing response data: {e}",
                details={"session_id": session_id, "original_error": str(e)},
            ) from e

    async def process_streaming_response(
        self,
        response_iterator: AsyncIterator[Any],
        session_id: str,
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[ProcessedResponse]:
        """Process a streaming response through the unified pipeline.

        Args:
            response_iterator: An async iterator yielding raw response chunks.
            session_id: The ID of the current session.
            context: Optional context dictionary with additional metadata.

        Returns:
            An async iterator yielding ProcessedResponse objects.
        """
        # Reset loop detector state at the beginning of each streaming session
        # to prevent contamination across different requests
        # Loop detector is optional - processors handle it via DI if needed
        loop_detector: ILoopDetector | None = None
        if self._loop_detector_factory:
            try:
                loop_detector = self._loop_detector_factory()
                # Reset loop detector state at the beginning of each streaming session
                if loop_detector is not None:
                    loop_detector.reset()
            except (TypeError, AttributeError, RuntimeError):
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Failed to create loop detector from factory", exc_info=True
                    )
        # No fallback construction - loop detector is optional and handled via DI (requirement 5.2)

        # Inject context into iterator if provided
        # This ensures downstream processors (like middleware) have access to
        # request context via metadata, even for raw chunks.
        effective_iterator = response_iterator
        if context:

            async def _context_injector(it: AsyncIterator[Any]) -> AsyncIterator[Any]:
                async for chunk in it:
                    # Attach context metadata without nesting ProcessedResponse objects.
                    # Downstream processors can handle ProcessedResponse directly, but
                    # nested ProcessedResponse(content=ProcessedResponse(...)) can
                    # confuse normalizers and lead to empty streams.
                    if isinstance(chunk, ProcessedResponse):
                        merged_metadata = dict(chunk.metadata or {})
                        for key, value in context.items():
                            merged_metadata.setdefault(key, value)
                        yield ProcessedResponse(
                            content=chunk.content,
                            usage=chunk.usage,
                            metadata=merged_metadata,
                        )
                    else:
                        # Wrap raw chunks in ProcessedResponse to carry context.
                        yield ProcessedResponse(content=chunk, metadata=context)

            effective_iterator = _context_injector(response_iterator)

        # For the basic streaming tests without a mock normalizer, we need to handle
        # the raw chunks directly
        if self._stream_normalizer is None:
            async for chunk in effective_iterator:
                # Convert chunk to ProcessedResponse
                if isinstance(chunk, StreamingChatResponse):
                    metadata: dict[str, Any] = {"model": chunk.model}
                    if session_id:
                        metadata["session_id"] = session_id
                    yield ProcessedResponse(
                        content=chunk.content or "",
                        metadata=metadata,
                        usage=None,
                    )
                elif isinstance(chunk, ProcessedResponse):
                    # Preserve metadata supplied by upstream processors
                    metadata = dict(chunk.metadata or {})
                    if session_id and "session_id" not in metadata:
                        metadata["session_id"] = session_id
                    yield ProcessedResponse(
                        content=chunk.content,
                        metadata=metadata,
                        usage=chunk.usage,
                    )
                elif isinstance(chunk, dict) and "choices" in chunk:
                    content = ""
                    if (
                        chunk.get("choices")
                        and "delta" in chunk["choices"][0]
                        and "content" in chunk["choices"][0]["delta"]
                    ):
                        content = chunk["choices"][0]["delta"]["content"]
                    metadata = {"session_id": session_id} if session_id else {}
                    yield ProcessedResponse(
                        content=content, metadata=metadata, usage=None
                    )
                elif isinstance(chunk, bytes):
                    # Try to parse as SSE
                    try:
                        text = chunk.decode("utf-8").strip()
                        if text.startswith("data: "):
                            text = text[6:].strip()
                            data = json.loads(text)
                            content = ""
                            if (
                                data.get("choices")
                                and "delta" in data["choices"][0]
                                and "content" in data["choices"][0]["delta"]
                            ):
                                content = data["choices"][0]["delta"]["content"]
                            yield ProcessedResponse(
                                content=content,
                                metadata=(
                                    {"session_id": session_id} if session_id else {}
                                ),
                                usage=None,
                            )
                    except json.JSONDecodeError:
                        # Just yield the raw bytes as string
                        yield ProcessedResponse(
                            content=str(chunk),
                            metadata={"session_id": session_id} if session_id else {},
                            usage=None,
                        )
                else:
                    # Default handling for unknown types
                    yield ProcessedResponse(
                        content=str(chunk),
                        metadata={"session_id": session_id} if session_id else {},
                        usage=None,
                    )
            return

        # Process the stream using the unified pipeline
        try:
            # Wrap response iterator with memory capture if enabled
            capture_processor: ResponseCaptureProcessor | None = None

            if self._memory_capture:
                # We need to hook into the stream *before* it gets consumed by the pipeline
                # BUT wait, the pipeline consumes StreamingContent.
                # If we hook here, we get raw chunks.
                # ResponseCaptureProcessor expects StreamingContent.
                # So we should ideally inject it into the pipeline or wrap the pipeline output.
                #
                # However, wrapping the pipeline output means we only capture what comes OUT.
                # But ResponseCaptureProcessor is an IStreamProcessor designed for the pipeline.
                #
                # The issue is that IStreamProcessor logic is inside StreamNormalizer which is instantiated in __init__.
                # We can't inject per-request processors easily into StreamNormalizer without modifying it.
                #
                # Alternative: Use a wrapper around the output stream of pipeline.
                # The pipeline outputs StreamingContent (when format="objects").
                # So we can just feed that into ResponseCaptureProcessor.process().
                capture_processor = ResponseCaptureProcessor(
                    self._memory_capture, session_id
                )

            stream_processor = self._unified_pipeline.process_streaming(
                effective_iterator,
                session_id,
                output_format="objects",
                cancel_callback=None,
            )

            async for processed_chunk in stream_processor:
                # Feed to capture processor if enabled
                if capture_processor and isinstance(processed_chunk, StreamingContent):
                    try:
                        # process() is async and returns content (pass-through)
                        # We await it to ensure capture logic runs
                        await capture_processor.process(processed_chunk)
                    except Exception as e:
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug("Memory capture error: %s", e)

                if isinstance(processed_chunk, StreamingContent):
                    chunk_content: str | dict[str, Any] = self._normalize_chunk_text(
                        processed_chunk.content
                    )
                    source_metadata = processed_chunk.metadata or {}
                    metadata = dict(source_metadata)
                    if session_id:
                        metadata.setdefault("session_id", session_id)
                    metadata.setdefault("model", source_metadata.get("model"))
                    metadata.setdefault("id", source_metadata.get("id"))
                    metadata.setdefault("created", source_metadata.get("created"))
                    metadata["is_done"] = processed_chunk.is_done
                    metadata["is_cancellation"] = processed_chunk.is_cancellation
                    # Preserve stream_id for downstream buffering correlation
                    if processed_chunk.stream_id:
                        metadata["stream_id"] = processed_chunk.stream_id
                    elif "stream_id" in source_metadata:
                        metadata["stream_id"] = source_metadata["stream_id"]
                    yield ProcessedResponse(
                        content=chunk_content,
                        usage=processed_chunk.usage,
                        metadata=metadata,
                    )
                elif isinstance(processed_chunk, ProcessedResponse):
                    # Extract content from ProcessedResponse
                    normalized: str | dict[str, Any] = self._normalize_chunk_text(
                        processed_chunk.content
                    )
                    metadata = (
                        dict(processed_chunk.metadata)
                        if processed_chunk.metadata
                        else {}
                    )
                    if session_id:
                        metadata.setdefault("session_id", session_id)
                    yield ProcessedResponse(
                        content=normalized,
                        usage=processed_chunk.usage,
                        metadata=metadata,
                    )
                else:
                    # Handle unexpected types
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            f"Unexpected chunk type from stream normalizer: {type(processed_chunk)}"
                        )
                    metadata = {"session_id": session_id} if session_id else {}
                    yield ProcessedResponse(
                        content=str(processed_chunk),
                        usage=None,
                        metadata=metadata,
                    )

        except (
            TypeError,
            ValueError,
            json.JSONDecodeError,
            AttributeError,
            KeyError,
        ) as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Error in stream processing: {e}", exc_info=True)
            yield ProcessedResponse(
                content=f"Error in stream processing: {e}",
                usage=None,
                metadata={
                    "error": True,
                    **({"session_id": session_id} if session_id else {}),
                },
            )

    @staticmethod
    def _normalize_chunk_text(chunk: Any) -> str | dict[str, Any]:
        """Normalize streaming payloads into client-friendly form.

        For OpenAI-format chunks (dicts with 'choices'), preserve the structure
        so downstream code (e.g., to_bytes()) can handle them properly.
        Other dicts are stringified to JSON.
        """
        if chunk is None:
            return ""
        if isinstance(chunk, dict):
            # Preserve OpenAI-format chunks as dicts for proper downstream handling
            # This includes usage-only chunks (choices: []) and regular content chunks
            if "choices" in chunk:
                return chunk
            # Other structured payloads become JSON strings
            return json.dumps(chunk)
        if isinstance(chunk, str):
            return chunk
        if isinstance(chunk, bytes | bytearray):
            try:
                return chunk.decode("utf-8")
            except UnicodeDecodeError:
                return chunk.decode("utf-8", errors="ignore")
        return str(chunk)
