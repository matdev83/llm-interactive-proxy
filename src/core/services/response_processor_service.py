from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any, cast

from src.core.common.exceptions import (
    LoopDetectionError,
    ParsingError,
)
from src.core.domain.chat import StreamingChatResponse
from src.core.domain.streaming_response_processor import (
    IStreamProcessor,
    StreamingContent,
)
from src.core.interfaces.loop_detector_interface import ILoopDetector
from src.core.interfaces.middleware_application_manager_interface import (
    IMiddlewareApplicationManager,
)
from src.core.interfaces.response_parser_interface import IResponseParser
from src.core.interfaces.response_processor_interface import (
    IResponseMiddleware,
    IResponseProcessor,
    ProcessedResponse,
)
from src.core.interfaces.streaming_response_processor_interface import IStreamNormalizer
from src.core.services.streaming.content_accumulation_processor import (
    ContentAccumulationProcessor,
)
from src.core.services.streaming.stream_context_registry import (
    get_global_streaming_context_registry,
)
from src.core.services.streaming.stream_normalizer import StreamNormalizer
from src.core.utils.json_intent import infer_expected_json

logger = logging.getLogger(__name__)


class ResponseProcessor(IResponseProcessor):
    def __init__(
        self,
        response_parser: IResponseParser,
        middleware_application_manager: IMiddlewareApplicationManager,
        app_state: Any | None = None,
        loop_detector: ILoopDetector | None = None,
        stream_normalizer: IStreamNormalizer | None = None,
        tool_call_repair_processor: IStreamProcessor | None = None,
        loop_detection_processor: IStreamProcessor | None = None,
        content_accumulation_processor: IStreamProcessor | None = None,
        middleware_application_processor: IStreamProcessor | None = None,
        middleware_list: list[IResponseMiddleware] | None = None,
    ) -> None:
        self._app_state = app_state
        self._background_tasks: list[asyncio.Task[Any]] = []
        self._loop_detector = loop_detector  # Set loop detector
        self._response_parser = response_parser
        self._middleware_application_manager = middleware_application_manager
        self._middleware_list = middleware_list or []

        # Angel feature wiring
        self._angel_service: Any | None = None
        self._angel_frequency: int = 1

        self._stream_normalizer = stream_normalizer

        if stream_normalizer is None:
            processors: list[IStreamProcessor] = []

            # Use new decomposed processors if provided
            if tool_call_repair_processor is not None:
                processors.append(tool_call_repair_processor)
            if loop_detection_processor is not None:
                processors.append(loop_detection_processor)
            if content_accumulation_processor is not None:
                processors.append(content_accumulation_processor)
            if middleware_application_processor is not None:
                processors.append(middleware_application_processor)

            if processors:
                if content_accumulation_processor is None:
                    registry = get_global_streaming_context_registry()
                    processors.append(
                        ContentAccumulationProcessor(
                            max_buffer_bytes=10 * 1024 * 1024, registry=registry
                        )
                    )

                self._stream_normalizer = StreamNormalizer(processors)

        if self._stream_normalizer is None:
            raise RuntimeError(
                "ResponseProcessor requires an IStreamNormalizer; "
                "ensure the streaming pipeline is registered."
            )

    async def _apply_angel_verification(
        self, original_request: Any, content: Any
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
                except Exception:
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
                    except Exception:
                        return value.decode("utf-8", errors="ignore")
                return str(value)

            angel_response = await backend_service.chat_completions(
                verification_request, stream=False, allow_failover=True, context=None
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

            corrected_response = await backend_service.chat_completions(
                correction_request, stream=False, allow_failover=True, context=None
            )
            corrected_text = _extract_text(corrected_response)

            if svc.has_override_marker(corrected_text):
                return {"action": "pass"}

            cleaned = svc.strip_override_marker(corrected_text)
            return {"action": "steer", "corrected_content": cleaned}
        except Exception:
            logger.debug("Angel verification internal error", exc_info=True)
            return None

    def add_background_task(self, task: asyncio.Task[Any]) -> None:
        """Add a background task to be managed by the processor."""
        self._background_tasks.append(task)

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
        """Process a non-streaming response.

        Args:
            response: The response object from the backend.
            session_id: The ID of the current session.

        Returns:
            A ProcessedResponse object.

        Raises:
            BackendError: If there is an error processing the response.
            LoopDetectionError: If a loop is detected in the response.
        """
        try:
            # Parse the raw response using the injected parser
            parsed_data = self._response_parser.parse_response(response)
            content = self._response_parser.extract_content(parsed_data)
            usage = self._response_parser.extract_usage(parsed_data)
            metadata = self._response_parser.extract_metadata(parsed_data) or {}

            # Check for loops if loop detector is available
            if self._loop_detector is not None and isinstance(
                content, str
            ):  # Ensure content is string for loop detection
                loop_result = await self._loop_detector.check_for_loops(content)
                if loop_result.has_loop:
                    # Add loop detection metadata
                    metadata["loop_detected"] = True
                    metadata["loop_pattern"] = loop_result.pattern
                    metadata["loop_repetitions"] = loop_result.repetitions
                    # For tests expecting an exception, raise LoopDetectionError
                    # In a future release, this behavior should be configurable
                    raise LoopDetectionError(
                        message=f"Loop detected: {loop_result.pattern} repeated {loop_result.repetitions} times",
                        details={
                            "pattern": loop_result.pattern,
                            "repetitions": loop_result.repetitions,
                            "session_id": session_id,
                        },
                    )

            # Leave status as-is; allow upstream layers to decide error mapping.

            processed_response = ProcessedResponse(
                content=content, usage=usage, metadata=metadata
            )

            # Angel verification for non-streaming responses
            try:
                original_request = None
                if context and isinstance(context, dict):
                    original_request = context.get("original_request")
                # Only run when angel is configured in session
                if original_request is not None:
                    decision = await self._apply_angel_verification(
                        original_request, processed_response.content or ""
                    )
                    if decision and decision.get("action") == "steer":
                        corrected = decision.get("corrected_content", "")
                        processed_response.content = corrected
            except Exception:
                # Be conservative: do not break normal flow on Angel errors
                logger.debug("Angel verification failed; continuing", exc_info=True)

            # Apply middleware using the new manager if available
            if self._middleware_application_manager is not None:
                # Prepare metadata for middleware
                enriched_metadata: dict[str, Any] = {
                    "session_id": session_id,
                    "non_streaming": True,
                    **processed_response.metadata,
                }
                if "expected_json" not in enriched_metadata and infer_expected_json(
                    enriched_metadata, processed_response.content
                ):
                    enriched_metadata["expected_json"] = True

                middleware_context: dict[str, Any] = {
                    "stop_event": None,
                    "original_response": parsed_data,
                }
                if context:
                    middleware_context.update(context)

                # Assuming middleware application manager can handle non-streaming content directly
                processed_content = (
                    await self._middleware_application_manager.apply_middleware(
                        content=processed_response.content or "",
                        middleware_list=self._middleware_list,
                        is_streaming=False,
                        stop_event=None,
                        session_id=session_id,
                        context=middleware_context,
                    )
                )

                # Update processed_response with the result from middleware
                processed_response = ProcessedResponse(
                    content=processed_content,
                    usage=processed_response.usage,  # Usage and original metadata remain
                    metadata={
                        k: v
                        for k, v in enriched_metadata.items()
                        if k not in ("session_id", "non_streaming")
                    },
                )

                # If tool calls were detected by reactor, ensure they are persisted into metadata
                try:
                    detected_tool_calls = middleware_context.get("detected_tool_calls")
                    if isinstance(detected_tool_calls, list):
                        processed_response.metadata.setdefault("tool_calls", [])
                        if not processed_response.metadata["tool_calls"]:
                            processed_response.metadata["tool_calls"] = list(
                                detected_tool_calls
                            )
                except Exception:
                    logger.debug(
                        "Failed to persist detected tool calls into response metadata",
                        exc_info=True,
                    )

            return processed_response

        except LoopDetectionError:
            # Propagate loop detection as-is
            raise
        except json.JSONDecodeError as e:
            logger.error(
                f"JSON decoding error in non-streaming response: {e}", exc_info=True
            )
            raise ParsingError(
                message=f"Failed to decode JSON in response: {e}",
                details={"session_id": session_id, "original_error": str(e)},
            ) from e
        except (TypeError, ValueError, AttributeError, KeyError, IndexError) as e:
            # Catch common expected exceptions for data processing
            logger.error(
                f"Data processing error in non-streaming response: {e}", exc_info=True
            )
            raise ParsingError(
                message=f"Error processing response data: {e}",
                details={"session_id": session_id, "original_error": str(e)},
            ) from e

    async def process_streaming_response(
        self, response_iterator: AsyncIterator[Any], session_id: str
    ) -> AsyncIterator[ProcessedResponse]:
        """Process a streaming response using the configured stream normalizer.

        Args:
            response_iterator: An async iterator yielding raw response chunks.
            session_id: The ID of the current session.

        Returns:
            An async iterator yielding ProcessedResponse objects.
        """
        # Reset loop detector state at the beginning of each streaming session
        # to prevent contamination across different requests
        if self._loop_detector is not None:
            self._loop_detector.reset()

        # Ensure stream processors start clean for each streaming request so
        # buffered content from previous sessions cannot leak forward.
        if self._stream_normalizer is not None:
            reset_method = getattr(self._stream_normalizer, "reset", None)
            if callable(reset_method):
                try:
                    reset_method()
                except Exception as exc:
                    logger.debug(
                        "Failed to reset stream normalizer state: %s",
                        exc,
                        exc_info=True,
                    )

        # For the basic streaming tests without a mock normalizer, we need to handle
        # the raw chunks directly
        if self._stream_normalizer is None:
            async for chunk in response_iterator:
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

        # Process the stream using the normalizer
        try:
            # Process the stream using the normalizer
            try:
                stream_processor = self._stream_normalizer.process_stream(
                    response_iterator,
                    output_format="objects",
                    cancel_callback=None,
                )

                # stream_processor is already an async generator, no need to await

                async for processed_chunk in stream_processor:
                    if isinstance(processed_chunk, StreamingContent):
                        content = self._normalize_chunk_text(processed_chunk.content)
                        source_metadata = processed_chunk.metadata or {}
                        metadata = dict(source_metadata)
                        if session_id:
                            metadata.setdefault("session_id", session_id)
                        metadata.setdefault("model", source_metadata.get("model"))
                        metadata.setdefault("id", source_metadata.get("id"))
                        metadata.setdefault("created", source_metadata.get("created"))
                        metadata["is_done"] = processed_chunk.is_done
                        metadata["is_cancellation"] = processed_chunk.is_cancellation
                        yield ProcessedResponse(
                            content=content,
                            usage=processed_chunk.usage,  # Preserve usage when provided
                            metadata=metadata,
                        )
                    else:
                        # Handle cases where processed_chunk might be ProcessedResponse or other types
                        if isinstance(processed_chunk, ProcessedResponse):
                            # Extract content from ProcessedResponse
                            content = self._normalize_chunk_text(
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
                                content=content,
                                usage=processed_chunk.usage,
                                metadata=metadata,
                            )
                        else:
                            # Handle unexpected types
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
            ) as inner_e:
                # Catch common expected exceptions; others will be caught by the global error handler
                logger.error(f"Error in stream processing: {inner_e}", exc_info=True)
                yield ProcessedResponse(
                    content=f"Error in stream processing: {inner_e}",
                    usage=None,
                    metadata={
                        "error": True,
                        **({"session_id": session_id} if session_id else {}),
                    },
                )
        except json.JSONDecodeError as e:
            logger.error(
                f"JSON decoding error in streaming response: {e}", exc_info=True
            )
            yield ProcessedResponse(
                content=f"Error decoding JSON in stream: {e}",
                usage=None,
                metadata={
                    "error": True,
                    "original_error": str(e),
                    **({"session_id": session_id} if session_id else {}),
                },
            )
        except (TypeError, ValueError, AttributeError, KeyError) as e:
            # Catch common expected exceptions for data processing
            logger.error(
                f"Data processing error in streaming response: {e}", exc_info=True
            )
            yield ProcessedResponse(
                content=f"Error processing streaming data: {e}",
                usage=None,
                metadata={
                    "error": True,
                    "original_error": str(e),
                    **({"session_id": session_id} if session_id else {}),
                },
            )

    @staticmethod
    def _normalize_chunk_text(chunk: Any) -> str:
        """Normalize streaming payloads into string form."""
        if chunk is None:
            return ""
        if isinstance(chunk, str):
            return chunk
        if isinstance(chunk, bytes | bytearray):
            try:
                return chunk.decode("utf-8")
            except UnicodeDecodeError:
                return chunk.decode("utf-8", errors="ignore")
        if isinstance(chunk, dict):
            try:
                return json.dumps(chunk)
            except (TypeError, ValueError):
                return str(chunk)
        return str(chunk)
