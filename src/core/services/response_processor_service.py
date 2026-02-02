from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any


from pydantic.types import JsonValue

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
from src.core.services.streaming.chunk_normalizer import (
    normalize_to_processed_chunk_content,
)
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
        self._angel_frequency: int = 10

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
                frequency_value: int | None = 10
                max_history_value: int | None = None
                try:
                    cfg = (
                        self._app_state.get_setting("app_config")
                        if self._app_state
                        else None
                    )
                    session_cfg = getattr(cfg, "session", None)
                    model_spec = getattr(session_cfg, "angel_model", None)
                    frequency_value = getattr(session_cfg, "angel_frequency", 10)
                    max_history_value = getattr(session_cfg, "angel_max_history", None)
                    max_consecutive_failures = getattr(
                        session_cfg, "angel_max_consecutive_failures", 5
                    )
                    cooldown_seconds = getattr(session_cfg, "angel_cooldown_seconds", 300)
                except (AttributeError, TypeError, KeyError):
                    model_spec = None
                    frequency_value = 10
                    max_history_value = None
                    max_consecutive_failures = 5
                    cooldown_seconds = 300

                from typing import cast
                from src.core.di.services import get_service
                from src.core.interfaces.notification_service_interface import (
                    INotificationService,
                )

                notification_service = get_service(
                    cast(Any, INotificationService)
                )  # type: ignore[type-abstract]

                angel_svc = AngelService(
                    model_spec or "",
                    max_history=max_history_value,
                    max_consecutive_failures=max_consecutive_failures,
                    cooldown_seconds=cooldown_seconds,
                    notification_service=notification_service,
                )


                if not angel_svc.is_enabled() or not angel_svc.is_healthy():
                    if not angel_svc.is_enabled():
                        return {"action": "pass"}
                    else:
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "Angel verification skipped due to circuit breaker for model %s",
                                model_spec,
                            )
                        return {"action": "pass"}

                self._angel_service = angel_svc

                try:
                    freq_int = (
                        int(frequency_value) if frequency_value is not None else 10
                    )
                except (TypeError, ValueError):
                    freq_int = 10
                self._angel_frequency = freq_int if freq_int > 0 else 1

            svc: AngelService = self._angel_service

            if not isinstance(original_request, ChatRequest):
                return {"action": "pass"}

            # Resolve RequestContext from context dict (used for cancellation and Angel gating)
            request_context: RequestContext | None = None
            if context:
                candidate = context.get("request_context")
                if isinstance(candidate, RequestContext):
                    request_context = candidate

            # Never run Angel for tool-result continuation requests.
            try:
                if AngelService.is_tool_result_followup_request(original_request):
                    return {"action": "pass"}
            except Exception:
                # Fail-open: if detection fails, continue.
                pass

            # Never run Angel when a random replacement model is active.
            try:
                if request_context and request_context.extensions.get(
                    "model_replacement_active"
                ):
                    return {"action": "pass"}
            except Exception:
                pass

            frequency = getattr(self, "_angel_frequency", 10)

            # Prefer explicit per-request eligible turn counter (computed upstream).
            eligible_turn_count: int | None = None
            if request_context is not None:
                raw_count = request_context.extensions.get("angel_eligible_turn_count")
                try:
                    if isinstance(raw_count, int):
                        eligible_turn_count = raw_count
                    elif isinstance(raw_count, float | str):
                        eligible_turn_count = int(raw_count)
                except Exception:
                    eligible_turn_count = None

            if eligible_turn_count is not None:
                freq_int = int(frequency) if int(frequency) > 0 else 1
                if eligible_turn_count <= 0 or (eligible_turn_count % freq_int) != 0:
                    return {"action": "pass"}
            else:
                if not AngelService.should_run_for_request(original_request, frequency):
                    return {"action": "pass"}

            verification_request = svc.build_verification_request(
                original_request, content
            )

            # request_context already resolved above

            # Cancellation gate: ensure session is not cancelled before Angel verification backend call
            if self._cancellation_coordinator and request_context:
                session_key = resolve_session_key_from_request_context(request_context)
                if session_key:
                    self._cancellation_coordinator.ensure_not_cancelled(session_key)

            from typing import Any, cast

            provider = get_service_provider()
            backend_service: IBackendService = provider.get_required_service(  # type: ignore[reportUnknownVariableType]
                cast(Any, IBackendService)
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


            # Call Angel model with fail-open
            try:
                angel_response = await backend_service.chat_completions(  # type: ignore[reportUnknownMemberType]
                    verification_request,
                    stream=False,
                    allow_failover=True,
                    context=request_context,
                )
                angel_text = _extract_text(angel_response)
                await svc.report_success()

            except Exception as e:
                await svc.report_failure()

                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Angel model call failed (%s); failing-open",
                        type(e).__name__,
                        exc_info=True,
                    )
                return {"action": "pass"}

            decision = svc.parse_angel_output(angel_text)
            if decision.decision == "pass":
                return {"action": "pass"}

            steering_msg = (decision.steering_message or "").strip()
            if not steering_msg:
                return {"action": "pass"}

            correction_request = svc.build_correction_request(
                original_request, content, steering_msg
            )

            # Tag the angel steering message as non-forwardable and set injection boundary
            if correction_request.messages and request_context:
                from typing import cast

                from src.core.domain.non_forwardable import NonForwardableTagScope
                from src.core.interfaces.non_forwardable_interface import (
                    INonForwardableMessageIdentityService,
                    INonForwardableMessageRegistry,
                )
                from src.core.services.non_forwardable_message_enforcer import (
                    PROXY_INJECTED_MESSAGES_START_INDEX_KEY,
                )

                # Get registry and identity service from provider
                non_forwardable_registry = None
                non_forwardable_identity_service = None
                
                if provider:
                    non_forwardable_registry = provider.get_service(
                        cast(type, INonForwardableMessageRegistry)
                    )
                    non_forwardable_identity_service = provider.get_service(
                        cast(type, INonForwardableMessageIdentityService)
                    )

                # Find the steering message (last user message with steering marker)
                steering_message = None
                for msg in reversed(correction_request.messages):
                    if msg.role == "user" and "ANGEL STEERING" in (
                        str(msg.content) or ""
                    ):
                        steering_message = msg
                        break

                if (
                    steering_message
                    and non_forwardable_registry
                    and non_forwardable_identity_service
                ):
                    session_id = request_context.session_id or "unknown"
                    try:
                        identity = non_forwardable_identity_service.compute_identity(  # type: ignore[reportUnknownMemberType]
                            steering_message
                        )
                        await non_forwardable_registry.tag_identities(  # type: ignore[reportUnknownMemberType]
                            session_id=session_id,
                            identities=[identity],
                            scope=NonForwardableTagScope.CLIENT_HISTORY_ONLY,
                            reason="angel_steering",
                        )
                        # Set injection boundary
                        injection_start_index = len(original_request.messages)
                        # extensions is dict[str, JsonValue] (not None), so no need to check
                        request_context.extensions[
                            PROXY_INJECTED_MESSAGES_START_INDEX_KEY
                        ] = injection_start_index
                    except Exception as e:
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                "Failed to tag angel steering message as non-forwardable: %s",
                                e,
                                exc_info=True,
                            )

            # Cancellation gate: ensure session is not cancelled before Angel correction backend call
            if self._cancellation_coordinator and request_context:
                session_key = resolve_session_key_from_request_context(request_context)
                if session_key:
                    self._cancellation_coordinator.ensure_not_cancelled(session_key)

            # Call correction with fail-open
            try:
                corrected_response = await backend_service.chat_completions(  # type: ignore[reportUnknownMemberType]
                    correction_request,
                    stream=False,
                    allow_failover=True,
                    context=request_context,
                )
                corrected_text = _extract_text(corrected_response)

                # Prevent internal override markers from reaching the client.
                # If the correction is *only* an override marker (or becomes empty after stripping),
                # fail-open to the original response content.
                cleaned = re.sub(
                    r"<override_angel>[\s\S]*?</override_angel>",
                    "",
                    str(corrected_text or ""),
                    flags=re.IGNORECASE,
                )
                cleaned = re.sub(
                    r"<override_angel\s*/\s*>",
                    "",
                    cleaned,
                    flags=re.IGNORECASE,
                ).strip()

                if not cleaned:
                    return {"action": "pass"}

                return {"action": "steer", "corrected_content": cleaned}
            except Exception as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Angel correction call failed (%s); failing-open",
                        type(e).__name__,
                        exc_info=True,
                    )
                return {"action": "pass"}

        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Angel verification encountered unexpected error (%s); failing-open",
                    type(e).__name__,
                    exc_info=True,
                )
            return {"action": "pass"}

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
        context: RequestContext | None = None,
    ) -> ProcessedResponse:
        """Process a non-streaming response through the unified pipeline.

        This method wraps the response as a single-chunk stream, processes it
        through the same middleware chain as streaming responses, then unwraps
        the result back to a single ProcessedResponse.

        Args:
            response: The response object from the backend.
            session_id: The ID of the current session.
            context: Optional request context with processing metadata.

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

            # Normalize content to ProcessedChunkContent before building ProcessedResponse
            normalized_content = normalize_to_processed_chunk_content(content)

            # Normalize metadata to dict[str, JsonValue]
            normalized_metadata = self._normalize_metadata(metadata)

            # Build initial ProcessedResponse for pipeline
            initial_response = ProcessedResponse(
                content=normalized_content,
                usage=usage,
                metadata=normalized_metadata,
            )

            # Prepare context metadata for the pipeline
            # Extract values from RequestContext if provided
            pipeline_metadata: dict[str, Any] = {
                "original_response": parsed_data,
            }
            if context is not None:
                # Extract original_request from context
                if context.original_request is not None:
                    pipeline_metadata["original_request"] = context.original_request
                elif context.domain_request is not None:
                    pipeline_metadata["original_request"] = context.domain_request
                # Extract processing context values if available
                if context.processing_context is not None:
                    processing_values = context.processing_context.values
                    # ProcessingContext.values is dict[str, Any], no isinstance check needed
                    pipeline_metadata.update(processing_values)
                # Extract other context fields
                if context.backend is not None:
                    pipeline_metadata["backend_name"] = context.backend
                if context.effective_model is not None:
                    pipeline_metadata["model_name"] = context.effective_model
                if context.session_id is not None:
                    pipeline_metadata["session_id"] = context.session_id
                if context.request_id is not None:
                    pipeline_metadata["request_id"] = context.request_id
                if context.agent is not None:
                    pipeline_metadata["calling_agent"] = context.agent
                # Store RequestContext reference for cancellation gate resolution
                pipeline_metadata["request_context"] = context

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
                if context is not None:
                    original_request = (
                        context.original_request or context.domain_request
                    )
                # Only run when angel is configured in session

                if original_request is not None:
                    # Build context dict for angel verification (internal method expects dict)
                    angel_context: dict[str, Any] | None = None
                    if context is not None:
                        angel_context = {}
                        if context.processing_context is not None:
                            processing_values = context.processing_context.values
                            # ProcessingContext.values is dict[str, Any], no isinstance check needed
                            angel_context.update(processing_values)
                        # Provide RequestContext for cancellation and Angel gating.
                        angel_context["request_context"] = context
                    decision = await self._apply_angel_verification(
                        original_request,
                        processed_response.content or "",
                        angel_context,
                    )
                    if decision and decision.get("action") == "steer":
                        corrected = decision.get("corrected_content", "")
                        # Normalize content and metadata to ensure boundary safety
                        normalized_corrected = normalize_to_processed_chunk_content(
                            corrected
                        )
                        normalized_metadata = self._normalize_metadata(
                            processed_response.metadata
                        )
                        processed_response = ProcessedResponse(
                            content=normalized_corrected,
                            usage=processed_response.usage,
                            metadata=normalized_metadata,
                        )
            except (KeyError, TypeError, ValueError, AttributeError):
                # Be conservative: do not break normal flow on Angel errors
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Angel verification failed; continuing", exc_info=True
                    )

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
        context: RequestContext | None = None,
    ) -> AsyncIterator[ProcessedResponse]:
        """Process a streaming response through the unified pipeline.

        Args:
            response_iterator: An async iterator yielding raw response chunks.
            session_id: The ID of the current session.
            context: Optional request context with processing metadata.

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
        if context is not None:
            # Extract context values for metadata injection
            context_metadata: dict[str, Any] = {}
            if context.processing_context is not None:
                processing_values = context.processing_context.values
                # ProcessingContext.values is dict[str, Any], no isinstance check needed
                context_metadata.update(processing_values)
            if context.backend is not None:
                context_metadata["backend_name"] = context.backend
            if context.effective_model is not None:
                context_metadata["model_name"] = context.effective_model
            if context.session_id is not None:
                context_metadata["session_id"] = context.session_id
            if context.request_id is not None:
                context_metadata["request_id"] = context.request_id
            if context.agent is not None:
                context_metadata["calling_agent"] = context.agent
            if context.original_request is not None:
                context_metadata["original_request"] = context.original_request
            elif context.domain_request is not None:
                context_metadata["original_request"] = context.domain_request

            async def _context_injector(it: AsyncIterator[Any]) -> AsyncIterator[Any]:
                async for chunk in it:
                    # Attach context metadata without nesting ProcessedResponse objects.
                    # Downstream processors can handle ProcessedResponse directly, but
                    # nested ProcessedResponse(content=ProcessedResponse(...)) can
                    # confuse normalizers and lead to empty streams.
                    if isinstance(chunk, ProcessedResponse):
                        merged_metadata = dict(chunk.metadata or {})
                        merged_metadata.update(context_metadata)
                        # Normalize content and metadata to ensure boundary safety
                        normalized_content = normalize_to_processed_chunk_content(
                            chunk.content
                        )
                        normalized_metadata = self._normalize_metadata(merged_metadata)
                        yield ProcessedResponse(
                            content=normalized_content,
                            usage=chunk.usage,
                            metadata=normalized_metadata,
                        )
                    else:
                        # Wrap raw chunks in ProcessedResponse to carry context.
                        # Normalize chunk content and context metadata
                        normalized_content = normalize_to_processed_chunk_content(chunk)
                        normalized_metadata = self._normalize_metadata(context_metadata)
                        yield ProcessedResponse(
                            content=normalized_content, metadata=normalized_metadata
                        )

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
                    # Normalize content and metadata to ensure boundary safety
                    normalized_content = normalize_to_processed_chunk_content(
                        chunk.content or ""
                    )
                    normalized_metadata = self._normalize_metadata(metadata)
                    yield ProcessedResponse(
                        content=normalized_content,
                        metadata=normalized_metadata,
                        usage=None,
                    )
                elif isinstance(chunk, ProcessedResponse):
                    # Preserve metadata supplied by upstream processors
                    metadata = dict(chunk.metadata or {})
                    if session_id and "session_id" not in metadata:
                        metadata["session_id"] = session_id
                    # Normalize content and metadata to ensure boundary safety
                    normalized_content = normalize_to_processed_chunk_content(
                        chunk.content
                    )
                    normalized_metadata = self._normalize_metadata(metadata)
                    yield ProcessedResponse(
                        content=normalized_content,
                        metadata=normalized_metadata,
                        usage=chunk.usage,
                    )
                elif isinstance(chunk, dict) and "choices" in chunk:
                    content = ""
                    if (
                        chunk.get("choices")  # type: ignore[reportUnknownMemberType]
                        and "delta" in chunk["choices"][0]
                        and "content" in chunk["choices"][0]["delta"]
                    ):
                        content = chunk["choices"][0]["delta"]["content"]  # type: ignore[reportUnknownVariableType]
                    metadata = {"session_id": session_id} if session_id else {}
                    # Normalize content and metadata to ensure boundary safety
                    normalized_content = normalize_to_processed_chunk_content(content)
                    normalized_metadata = self._normalize_metadata(metadata)
                    yield ProcessedResponse(
                        content=normalized_content,
                        metadata=normalized_metadata,
                        usage=None,
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
                            # Normalize content and metadata to ensure boundary safety
                            normalized_content = normalize_to_processed_chunk_content(
                                content
                            )
                            chunk_metadata = (
                                {"session_id": session_id} if session_id else {}
                            )
                            normalized_metadata = self._normalize_metadata(
                                chunk_metadata
                            )
                            yield ProcessedResponse(
                                content=normalized_content,
                                metadata=normalized_metadata,
                                usage=None,
                            )
                    except json.JSONDecodeError:
                        # Just yield the raw bytes as string
                        # Normalize content and metadata to ensure boundary safety
                        normalized_content = normalize_to_processed_chunk_content(
                            str(chunk)
                        )
                        chunk_metadata = (
                            {"session_id": session_id} if session_id else {}
                        )
                        normalized_metadata = self._normalize_metadata(chunk_metadata)
                        yield ProcessedResponse(
                            content=normalized_content,
                            metadata=normalized_metadata,
                            usage=None,
                        )
                else:
                    # Default handling for unknown types
                    # Normalize content and metadata to ensure boundary safety
                    normalized_content = normalize_to_processed_chunk_content(  # type: ignore[reportUnknownArgumentType]
                        str(chunk)
                    )
                    chunk_metadata = {"session_id": session_id} if session_id else {}
                    normalized_metadata = self._normalize_metadata(chunk_metadata)
                    yield ProcessedResponse(
                        content=normalized_content,
                        metadata=normalized_metadata,
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
                    # Normalize content to ProcessedChunkContent before wrapping
                    chunk_content = normalize_to_processed_chunk_content(  # type: ignore[reportUnknownVariableType]
                        processed_chunk.content
                    )
                    source_metadata = processed_chunk.metadata or {}
                    # Normalize base metadata first
                    metadata = self._normalize_metadata(dict(source_metadata))
                    # Safely merge additional fields, ensuring all values are JSON-serializable
                    metadata = self._safe_merge_metadata(
                        metadata,
                        source_metadata,
                        ("is_done", processed_chunk.is_done),
                        ("is_cancellation", processed_chunk.is_cancellation),
                        *([("session_id", session_id)] if session_id else []),
                        *(
                            [("stream_id", processed_chunk.stream_id)]
                            if processed_chunk.stream_id
                            else []
                        ),
                    )
                    yield ProcessedResponse(
                        content=chunk_content,
                        usage=processed_chunk.usage,
                        metadata=metadata,
                    )
                elif isinstance(processed_chunk, ProcessedResponse):
                    # Normalize content to ProcessedChunkContent (ensure it's already normalized)
                    normalized_content = normalize_to_processed_chunk_content(
                        processed_chunk.content
                    )
                    # Normalize base metadata
                    metadata = self._normalize_metadata(
                        dict(processed_chunk.metadata)
                        if processed_chunk.metadata
                        else {}
                    )
                    # Safely merge session_id if provided
                    if session_id:
                        metadata = self._safe_merge_metadata(
                            metadata, {}, ("session_id", session_id)
                        )
                    yield ProcessedResponse(
                        content=normalized_content,
                        usage=processed_chunk.usage,
                        metadata=metadata,
                    )
                else:
                    # Handle unexpected types - normalize to ProcessedChunkContent
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            f"Unexpected chunk type from stream normalizer: {type(processed_chunk)}"
                        )
                    normalized_content = normalize_to_processed_chunk_content(
                        processed_chunk
                    )
                    metadata = self._normalize_metadata(
                        {"session_id": session_id} if session_id else {}
                    )
                    yield ProcessedResponse(
                        content=normalized_content,
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
            # Normalize error content and metadata
            error_content = normalize_to_processed_chunk_content(
                f"Error in stream processing: {e}"
            )
            error_metadata = self._normalize_metadata(
                {
                    "error": True,
                    **({"session_id": session_id} if session_id else {}),
                }
            )
            yield ProcessedResponse(
                content=error_content,
                usage=None,
                metadata=error_metadata,
            )

    @staticmethod
    def _normalize_metadata(metadata: dict[str, Any]) -> dict[str, JsonValue]:
        """Normalize metadata to dict[str, JsonValue] for boundary safety.

        Args:
            metadata: Raw metadata dictionary

        Returns:
            Normalized metadata with JSON-serializable values only
        """
        from src.core.domain.translation_utils.json_utils import (
            sanitize_dict_for_json,
        )

        # Sanitize metadata to ensure all values are JSON-serializable
        sanitized = sanitize_dict_for_json(metadata)

        # FIX: Restore tool_calls if lost during sanitization (e.g. recursion limits or bug)
        if "tool_calls" in metadata and not sanitized.get("tool_calls"):
            # Manually sanitize tool_calls list to ensure it survives
            raw_tools = metadata["tool_calls"]
            if isinstance(raw_tools, list):
                sanitized_tools = []
                for tool in raw_tools:
                    if isinstance(tool, dict) or type(tool) is dict:
                        # Create new dict to avoid reference issues
                        sanitized_tools.append(dict(tool))
                if sanitized_tools:
                    sanitized["tool_calls"] = sanitized_tools
        return sanitized

    @staticmethod
    def _safe_merge_metadata(
        normalized_metadata: dict[str, JsonValue],
        source_metadata: dict[str, Any],
        *additional_fields: tuple[str, Any],
    ) -> dict[str, JsonValue]:
        """Safely merge additional fields into normalized metadata.

        This helper ensures that values from source_metadata and additional_fields
        are normalized to JSON-serializable types before being added to the
        normalized metadata dict.

        Args:
            normalized_metadata: Already normalized metadata dict
            source_metadata: Source metadata dict that may contain non-JSON values
            *additional_fields: Additional (key, value) tuples to merge

        Returns:
            Normalized metadata dict with all values JSON-serializable
        """
        from src.core.domain.translation_utils.json_utils import (
            sanitize_dict_for_json,
        )

        # Create a dict with values to merge
        to_merge: dict[str, Any] = {}

        # Add values from source_metadata if they exist
        for key in ["model", "id", "created", "stream_id"]:
            if key in source_metadata:
                to_merge[key] = source_metadata[key]

        # Add additional fields
        for key, value in additional_fields:
            to_merge[key] = value

        # Normalize the merged values
        if to_merge:
            normalized_merge = sanitize_dict_for_json(to_merge)
            normalized_metadata = {**normalized_metadata, **normalized_merge}

        return normalized_metadata
