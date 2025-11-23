"""
Streaming pipeline orchestrator.

This module provides the orchestration layer that coordinates the flow
from backend → normalizer → processor chain → assembler.

This is the missing piece that wires together all the streaming infrastructure
components into a cohesive pipeline.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from src.core.ports.sse_assembler import SSEAssembler
from src.core.ports.streaming_contracts import (
    IStreamAssembler,
    IStreamNormalizer,
    IStreamProcessor,
    StreamingContent,
)
from src.core.ports.streaming_metrics import get_metrics_instance

logger = logging.getLogger(__name__)


class StreamingPipeline:
    """Orchestrates the complete streaming pipeline.

    This class coordinates the flow:
    Backend → Normalizer → Processor Chain → Assembler → Client

    It ensures that:
    1. Raw backend chunks are normalized to StreamingContent
    2. Middleware processors are applied in order
    3. Final output is assembled in the correct format (SSE, etc.)
    4. Metrics are collected throughout
    5. State is properly isolated per stream
    """

    def __init__(
        self,
        normalizer: IStreamNormalizer,
        processors: list[IStreamProcessor] | None = None,
        assembler: IStreamAssembler | None = None,
    ) -> None:
        """Initialize the streaming pipeline.

        Args:
            normalizer: The normalizer for converting backend chunks
            processors: Optional list of middleware processors
            assembler: Optional assembler for output formatting (defaults to SSE)
        """
        self.normalizer = normalizer
        self.processors = processors or []
        self.assembler = assembler or SSEAssembler()
        self._metrics = get_metrics_instance()

    async def process_stream(
        self,
        raw_stream: AsyncIterator[Any],
        provider: str,
        stream_id: str | None = None,
        output_format: str = "sse",
    ) -> AsyncIterator[bytes]:
        """Process a raw backend stream through the complete pipeline.

        This is the main entry point that orchestrates:
        1. Normalization (backend format → StreamingContent)
        2. Processing (apply middleware chain)
        3. Assembly (StreamingContent → client format)

        Args:
            raw_stream: Raw async iterator from backend
            provider: Provider name for context
            stream_id: Optional stream identifier
            output_format: Output format (default: "sse")

        Yields:
            Formatted bytes ready for client transmission
        """
        # Start metrics tracking
        if stream_id:
            self._metrics.start_stream(stream_id)

        try:
            # Step 1: Normalize backend chunks to StreamingContent
            normalized_stream = self.normalizer.normalize_stream(raw_stream, provider)

            # Step 2: Apply processor chain
            processed_stream = self._apply_processor_chain(normalized_stream, stream_id)

            # Step 3: Assemble to client format
            assembled_stream = self.assembler.assemble_stream(
                processed_stream, output_format
            )

            # Step 4: Yield formatted bytes
            async for chunk_bytes in assembled_stream:
                if stream_id:
                    self._metrics.increment_chunks_sent(stream_id)
                yield chunk_bytes

        except Exception as e:
            # Log error and increment error terminations
            logger.error(
                "Error in streaming pipeline",
                exc_info=True,
                extra={
                    "provider": provider,
                    "stream_id": stream_id,
                    "error": str(e),
                },
            )
            if stream_id:
                self._metrics.increment_error_terminations(stream_id)
            raise
        finally:
            # End metrics tracking
            if stream_id:
                self._metrics.end_stream(stream_id)

    async def _apply_processor_chain(
        self,
        stream: AsyncIterator[StreamingContent],
        stream_id: str | None,
    ) -> AsyncIterator[StreamingContent]:
        """Apply the processor chain to a stream of StreamingContent.

        This method:
        1. Resets all processors before starting
        2. Applies each processor in order
        3. Ensures [DONE] markers pass through
        4. Tracks middleware mutations

        Args:
            stream: Stream of StreamingContent chunks
            stream_id: Optional stream identifier

        Yields:
            Processed StreamingContent chunks
        """
        # Reset all processors for clean state
        for processor in self.processors:
            processor.reset()

        # Process each chunk through the chain
        async for chunk in stream:
            processed_chunk = chunk

            # Apply each processor in order
            for processor in self.processors:
                try:
                    processed_chunk = await processor.process(processed_chunk)
                except Exception as e:
                    logger.error(
                        "Error in processor",
                        exc_info=True,
                        extra={
                            "processor": type(processor).__name__,
                            "stream_id": stream_id,
                            "error": str(e),
                        },
                    )
                    # Continue with unprocessed chunk on error
                    # (fail-safe: don't break the stream)
                    break

            yield processed_chunk


def create_pipeline_for_provider(
    provider: str,
    processors: list[IStreamProcessor] | None = None,
) -> StreamingPipeline:
    """Factory function to create a pipeline for a specific provider.

    This function selects the appropriate normalizer based on the provider
    and creates a complete pipeline with the specified processors.

    Args:
        provider: Provider name ("openai", "anthropic", "gemini", etc.)
        processors: Optional list of middleware processors

    Returns:
        Configured StreamingPipeline instance

    Raises:
        ValueError: If provider is not supported
    """
    # Import normalizers here to avoid circular imports
    from src.core.ports.anthropic_normalizer import AnthropicStreamNormalizer
    from src.core.ports.gemini_normalizer import GeminiStreamNormalizer
    from src.core.ports.openai_normalizer import OpenAIStreamNormalizer

    # Select normalizer based on provider
    normalizer_map = {
        "openai": OpenAIStreamNormalizer,
        "anthropic": AnthropicStreamNormalizer,
        "gemini": GeminiStreamNormalizer,
    }

    normalizer_class = normalizer_map.get(provider.lower())
    if not normalizer_class:
        raise ValueError(
            f"Unsupported provider: {provider}. "
            f"Supported providers: {list(normalizer_map.keys())}"
        )

    # Create normalizer instance
    normalizer = normalizer_class()

    # Create and return pipeline
    return StreamingPipeline(
        normalizer=normalizer,
        processors=processors,
    )
