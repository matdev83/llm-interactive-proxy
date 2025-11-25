"""
Integration helpers for connecting backends to the streaming pipeline.

This module provides helper functions that backends can use to integrate
with the new streaming pipeline orchestrator.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.ports.streaming_contracts import IStreamProcessor, handle_streaming_error
from src.core.ports.streaming_orchestrator import create_pipeline_for_provider
from src.core.ports.streaming_processors import (
    LoopDetectionProcessor as PortsLoopDetectionProcessor,
)
from src.core.ports.streaming_processors import (
    ThinkTagsProcessor,
)
from src.core.ports.streaming_processors import (
    ToolCallRepairProcessor as PortsToolCallRepairProcessor,
)

logger = logging.getLogger(__name__)


async def integrate_streaming_pipeline(
    raw_stream: AsyncIterator[Any],
    provider: str,
    stream_id: str | None = None,
    enable_loop_detection: bool = True,
    enable_tool_call_repair: bool = True,
    enable_think_tags: bool = True,
    prompt_tokens: int | None = None,
    model_name: str | None = None,
) -> StreamingResponseEnvelope:
    """Integrate a raw backend stream with the streaming pipeline.

    This function:
    1. Creates a pipeline with the appropriate normalizer for the provider
    2. Adds configured processors (loop detection, tool call repair, etc.)
    3. Processes the stream through the complete pipeline
    4. Returns a StreamingResponseEnvelope with ProcessedResponse chunks

    This provides backward compatibility while using the new infrastructure.

    Args:
        raw_stream: Raw async iterator from backend's stream_completion()
        provider: Provider name ("openai", "anthropic", "gemini")
        stream_id: Optional stream identifier
        enable_loop_detection: Whether to enable loop detection processor
        enable_tool_call_repair: Whether to enable tool call repair processor
        enable_think_tags: Whether to enable think tags processor

    Returns:
        StreamingResponseEnvelope with processed chunks
    """
    processors: list[IStreamProcessor] = []

    def _resolve_processor(
        service_type: type[IStreamProcessor],
        fallback_factory: Callable[[], IStreamProcessor],
    ) -> IStreamProcessor:
        from src.core.di.services import get_or_build_service_provider

        provider = None
        try:
            provider = get_or_build_service_provider()
            resolved = provider.get_service(service_type)
            if resolved:
                return resolved
        except Exception:
            logger.debug(
                "Unable to resolve %s from DI provider; falling back to local instance.",
                service_type.__name__,
                exc_info=True,
            )

        return fallback_factory()

    def _default_loop_detection_processor() -> IStreamProcessor:
        return PortsLoopDetectionProcessor()

    def _default_tool_call_repair_processor() -> IStreamProcessor:
        return PortsToolCallRepairProcessor()

    if enable_loop_detection:
        processors.append(
            _resolve_processor(
                PortsLoopDetectionProcessor, _default_loop_detection_processor
            )
        )
    if enable_tool_call_repair:
        processors.append(
            _resolve_processor(
                PortsToolCallRepairProcessor, _default_tool_call_repair_processor
            )
        )
    if enable_think_tags:
        processors.append(_resolve_processor(ThinkTagsProcessor, ThinkTagsProcessor))

    # Add usage calculation processor if prompt tokens are provided
    # This ensures usage is calculated after all other processors (like loop detection)
    # have potentially modified the content.
    if prompt_tokens is not None and model_name:
        from src.core.ports.usage_processor import UsageCalculationProcessor

        def _usage_processor_factory() -> IStreamProcessor:
            return UsageCalculationProcessor(prompt_tokens=prompt_tokens, model_name=model_name)

        processors.append(_usage_processor_factory())

    # Create pipeline for the provider
    try:
        pipeline = create_pipeline_for_provider(provider, processors=processors)
    except ValueError as e:
        logger.error(
            "Failed to create streaming pipeline for provider %s: %s. No legacy fallback available.",
            provider,
            e,
        )

        error_chunk = await handle_streaming_error(e, stream_id, provider)

        async def error_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(content=error_chunk.to_bytes())

        return StreamingResponseEnvelope(
            content=error_stream(),
            media_type="text/event-stream",
            headers={},
        )

    # Process stream through pipeline
    async def processed_stream() -> AsyncIterator[ProcessedResponse]:
        """Wrap pipeline output in ProcessedResponse for backward compatibility."""
        try:
            async for sse_bytes in pipeline.process_stream(
                raw_stream,
                provider=provider,
                stream_id=stream_id,
                output_format="sse",
            ):
                # Wrap SSE bytes in ProcessedResponse for compatibility
                # The response adapter will handle these correctly
                yield ProcessedResponse(content=sse_bytes)
        except Exception as e:
            logger.error(
                "Error in streaming pipeline",
                exc_info=True,
                extra={
                    "provider": provider,
                    "stream_id": stream_id,
                    "error": str(e),
                },
            )
            error_chunk = await handle_streaming_error(e, stream_id, provider)
            yield ProcessedResponse(content=error_chunk.to_bytes())
            return
        finally:
            # Ensure raw stream is closed
            # Suppress errors for already-closed streams or streams that don't support aclose
            if hasattr(raw_stream, "aclose"):
                with contextlib.suppress(Exception):
                    await raw_stream.aclose()  # type: ignore

    async def cancel_callback() -> None:
        """Cancel the raw stream if possible."""
        if hasattr(raw_stream, "aclose"):
            await raw_stream.aclose()  # type: ignore

    return StreamingResponseEnvelope(
        content=processed_stream(),
        media_type="text/event-stream",
        headers={},
        cancel_callback=cancel_callback,
    )
