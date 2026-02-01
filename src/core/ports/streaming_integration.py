"""
Integration helpers for connecting backends to the streaming pipeline.

This module provides helper functions that backends can use to integrate
with the new streaming pipeline orchestrator.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import cast

from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.ports.streaming_contracts import IStreamProcessor, handle_streaming_error
from src.core.ports.streaming_orchestrator import (
    create_pipeline_for_provider,
    safe_aclose,
)
from src.core.ports.streaming_processors import (
    LoopDetectionProcessor as PortsLoopDetectionProcessor,
)
from src.core.ports.streaming_processors import ThinkTagsProcessor
from src.core.ports.streaming_processors import (
    ToolCallRepairProcessor as PortsToolCallRepairProcessor,
)
from src.core.services.streaming.chunk_normalizer import (
    normalize_to_processed_chunk_content,
)
from src.core.services.streaming.stream_context_registry import StreamingContextRegistry
from src.core.services.streaming.tool_call_repair_processor import (
    ToolCallRepairProcessor as ServiceToolCallRepairProcessor,
)
from src.core.services.streaming.vtc_postprocessor import VTCPostProcessor
from src.core.services.streaming.vtc_preprocessor import VTCPreProcessor
from src.core.services.tool_call_repair_service import ToolCallRepairService

logger = logging.getLogger(__name__)


async def integrate_streaming_pipeline(
    raw_stream: AsyncIterator[object],
    provider: str,
    stream_id: str | None = None,
    enable_loop_detection: bool = True,
    enable_tool_call_repair: bool = True,
    enable_think_tags: bool = True,
    prompt_tokens: int | None = None,
    model_name: str | None = None,
    vtc_enabled: bool = False,
    yield_interval: int = 100,
) -> StreamingResponseEnvelope:
    """Integrate a raw backend stream with the streaming pipeline.

    This function:
    1. Creates a pipeline with the appropriate normalizer for the provider
    2. Adds configured processors (loop detection, tool call repair, etc.)
    3. Processes the stream through the complete pipeline
    4. Returns a StreamingResponseEnvelope with ProcessedResponse chunks

    This provides backward compatibility while using the new infrastructure.

    Args:
        raw_stream: Raw async iterator from backend's stream_completion() (opaque provider-specific data)
        provider: Provider name ("openai", "anthropic", "gemini")
        stream_id: Optional stream identifier
        enable_loop_detection: Whether to enable loop detection processor
        enable_tool_call_repair: Whether to enable tool call repair processor
        enable_think_tags: Whether to enable think tags processor
        prompt_tokens: Optional prompt token count for usage calculation
        model_name: Optional model name for usage calculation
        vtc_enabled: Whether Virtual Tool Calling is enabled for this session
        yield_interval: Number of chunks to batch before yielding to event loop

    Returns:
        StreamingResponseEnvelope with processed chunks
    """
    processors: list[IStreamProcessor] = []

    # Lazy DI provider resolution - only fetch when needed.
    # This avoids triggering DI build hooks on simple streaming calls that don't need DI.
    _di_provider: IServiceProvider | None = None

    def _get_di_provider() -> IServiceProvider:
        nonlocal _di_provider
        if _di_provider is None:
            from src.core.di.services import get_or_build_service_provider

            _di_provider = get_or_build_service_provider()
        return _di_provider

    # VTC Pre-processor: FIRST in pipeline (converts XML to internal format)
    # This processor requires DI dependencies (StreamingContextRegistry)
    if vtc_enabled:
        di_provider = _get_di_provider()
        registry = di_provider.get_required_service(StreamingContextRegistry)
        processors.append(VTCPreProcessor(registry=registry))
        logger.debug("VTC pre-processor enabled for stream %s", stream_id)

    # Loop detection processor - stateless, can be created directly
    if enable_loop_detection:
        processors.append(PortsLoopDetectionProcessor())

    # Service-based tool call repair processor - requires DI dependencies
    if enable_tool_call_repair:
        di_provider = _get_di_provider()
        repair_service = di_provider.get_service(ToolCallRepairService)
        if repair_service is not None:
            registry = di_provider.get_required_service(StreamingContextRegistry)
            processors.append(
                ServiceToolCallRepairProcessor(
                    tool_call_repair_service=repair_service,
                    registry=registry,
                )
            )
        else:
            logger.warning(
                "ToolCallRepairService not available in DI container; "
                "skipping service-based tool call repair processor. "
                "Ports-based processor will still be used.",
                extra={"stream_id": stream_id, "provider": provider},
            )

    # Ports-based tool call repair processor - stateless, can be created directly
    if enable_tool_call_repair:
        processors.append(PortsToolCallRepairProcessor())

    # Think tags processor - stateless, can be created directly
    if enable_think_tags:
        processors.append(ThinkTagsProcessor())

    # Add usage calculation processor if prompt tokens are provided
    # This ensures usage is calculated after all other processors (like loop detection)
    # have potentially modified the content.
    if prompt_tokens is not None and model_name:
        from src.core.ports.usage_processor import UsageCalculationProcessor

        def _usage_processor_factory() -> IStreamProcessor:
            return cast(
                IStreamProcessor,
                UsageCalculationProcessor(
                    prompt_tokens=prompt_tokens, model_name=model_name
                ),
            )

        processors.append(_usage_processor_factory())

    # VTC Post-processor: LAST in pipeline (converts internal format back to XML)
    # This processor requires DI dependencies (StreamingContextRegistry)
    if vtc_enabled:
        di_provider = _get_di_provider()
        registry = di_provider.get_required_service(StreamingContextRegistry)
        processors.append(VTCPostProcessor(registry=registry))
        logger.debug("VTC post-processor enabled for stream %s", stream_id)

    # Create pipeline for the provider - normalizer must be constructed explicitly
    from src.core.ports.anthropic_normalizer import AnthropicStreamNormalizer
    from src.core.ports.gemini_normalizer import GeminiStreamNormalizer
    from src.core.ports.kiro_normalizer import KiroStreamNormalizer
    from src.core.ports.openai_normalizer import OpenAIStreamNormalizer

    # Select and construct normalizer based on provider (stateless adapter - no DI required)
    normalizer_map = {
        "openai": OpenAIStreamNormalizer,
        "anthropic": AnthropicStreamNormalizer,
        "gemini": GeminiStreamNormalizer,
        "kiro": KiroStreamNormalizer,
    }

    normalizer_class = normalizer_map.get(provider.lower())
    if not normalizer_class:
        logger.error(
            "Failed to create streaming pipeline for provider %s: Unsupported provider. "
            "No legacy fallback available.",
            provider,
        )
        error_chunk = await handle_streaming_error(
            ValueError(f"Unsupported provider: {provider}"), stream_id, provider
        )

        async def error_stream() -> AsyncIterator[ProcessedResponse]:
            normalized_content = normalize_to_processed_chunk_content(
                error_chunk.to_bytes()
            )
            yield ProcessedResponse(content=normalized_content)

        return StreamingResponseEnvelope(
            content=error_stream(),
            media_type="text/event-stream",
            headers={},
        )

    # Construct normalizer explicitly at call site (requirement 5.2)
    normalizer = normalizer_class()

    # Create pipeline for the provider
    try:
        pipeline = create_pipeline_for_provider(
            provider,
            processors=processors,
            normalizer=normalizer,
            yield_interval=yield_interval,
        )
    except ValueError as e:
        logger.error(
            "Failed to create streaming pipeline for provider %s: %s. No legacy fallback available.",
            provider,
            e,
            exc_info=True,
        )

        error_chunk = await handle_streaming_error(e, stream_id, provider)

        async def error_stream() -> AsyncIterator[ProcessedResponse]:
            normalized_content = normalize_to_processed_chunk_content(
                error_chunk.to_bytes()
            )
            yield ProcessedResponse(content=normalized_content)

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
                # Normalize SSE bytes to ProcessedChunkContent before wrapping
                normalized_content = normalize_to_processed_chunk_content(sse_bytes)
                # Wrap normalized content in ProcessedResponse for compatibility
                # The response adapter will handle these correctly
                yield ProcessedResponse(content=normalized_content)
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
            normalized_content = normalize_to_processed_chunk_content(
                error_chunk.to_bytes()
            )
            yield ProcessedResponse(content=normalized_content)
            return

    async def cancel_callback() -> None:
        """Cancel the raw stream if possible."""
        await safe_aclose(raw_stream, provider, stream_id)

    return StreamingResponseEnvelope(
        content=processed_stream(),
        media_type="text/event-stream",
        headers={},
        cancel_callback=cancel_callback,
    )
