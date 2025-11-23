"""
Integration helpers for connecting backends to the streaming pipeline.

This module provides helper functions that backends can use to integrate
with the new streaming pipeline orchestrator.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Any

from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.ports.streaming_contracts import IStreamProcessor
from src.core.ports.streaming_orchestrator import create_pipeline_for_provider
from src.core.ports.streaming_processors import (
    LoopDetectionProcessor,
    ThinkTagsProcessor,
    ToolCallRepairProcessor,
)

logger = logging.getLogger(__name__)


async def integrate_streaming_pipeline(
    raw_stream: AsyncIterator[Any],
    provider: str,
    stream_id: str | None = None,
    enable_loop_detection: bool = True,
    enable_tool_call_repair: bool = True,
    enable_think_tags: bool = True,
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
    from src.core.di.services import get_or_build_service_provider

    # Get service provider for resolving processors from DI container
    get_or_build_service_provider()

    processors: list[IStreamProcessor] = []

    try:
        from src.core.di.services import get_required_service

        if enable_loop_detection:
            processors.append(get_required_service(LoopDetectionProcessor))
        if enable_tool_call_repair:
            processors.append(get_required_service(ToolCallRepairProcessor))
        if enable_think_tags:
            processors.append(get_required_service(ThinkTagsProcessor))
    except Exception as e:
        logger.warning("Failed to get stream processors from DI container: %s", e)
        # Fallback to direct instantiation for tests
        try:
            if enable_loop_detection:
                processors.append(LoopDetectionProcessor())  # noqa: DI-bypass
            if enable_tool_call_repair:
                processors.append(ToolCallRepairProcessor())  # noqa: DI-bypass
            if enable_think_tags:
                processors.append(ThinkTagsProcessor())
        except Exception as fallback_error:
            logger.warning(
                "Failed to instantiate processors directly: %s", fallback_error
            )
            # Continue without processors - they're optional for basic streaming

    # Create pipeline for the provider
    try:
        pipeline = create_pipeline_for_provider(provider, processors=processors)
    except ValueError as e:
        logger.warning(
            "Failed to create pipeline for provider %s: %s. "
            "Falling back to pass-through mode.",
            provider,
            e,
        )

        # Fall back to pass-through mode
        async def passthrough_stream() -> AsyncIterator[ProcessedResponse]:
            async for chunk in raw_stream:
                yield ProcessedResponse(content=chunk)

        return StreamingResponseEnvelope(
            content=passthrough_stream(),
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
            # Yield error chunk
            yield ProcessedResponse(
                content=b"data: [DONE]\n\n",
                metadata={"error": str(e), "finish_reason": "error"},
            )
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
