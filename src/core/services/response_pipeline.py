"""
Unified response processing pipeline.

This module provides a single entry point for both streaming and non-streaming
response processing, treating non-streaming as a special case of streaming
(single chunk with is_done=True).

This eliminates code duplication between streaming and non-streaming paths
by routing all responses through the same processor chain.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.interfaces.streaming_response_processor_interface import IStreamNormalizer
from src.core.ports.streaming_contracts import StreamingContent
from src.core.services.streaming.non_streaming_adapter import NonStreamingAdapter

logger = logging.getLogger(__name__)


class UnifiedResponsePipeline:
    """Unified response processing pipeline for both streaming and non-streaming.

    This class provides a single code path for all response processing,
    treating non-streaming responses as a special case of streaming
    (single chunk with is_done=True).

    Benefits:
    - DRY: All middleware logic lives in one place
    - Consistent: Same processing guarantees for both modes
    - Maintainable: Changes only need to be made once

    Architecture:
        Non-streaming flow:
            Response → wrap_as_stream() → StreamNormalizer → unwrap_from_stream() → ProcessedResponse

        Streaming flow:
            AsyncIterator → StreamNormalizer → AsyncIterator[StreamingContent/bytes]
    """

    def __init__(
        self,
        stream_normalizer: IStreamNormalizer,
    ) -> None:
        """Initialize the unified pipeline.

        Args:
            stream_normalizer: The stream normalizer with processor chain
        """
        self._normalizer = stream_normalizer

    def process_streaming(
        self,
        response_iterator: AsyncIterator[Any],
        session_id: str,
        output_format: str = "objects",
        cancel_callback: Any | None = None,
    ) -> AsyncIterator[StreamingContent | bytes]:
        """Process a streaming response through the unified pipeline.

        Args:
            response_iterator: Raw chunks from backend
            session_id: Session identifier
            output_format: "sse" for bytes, "objects" for StreamingContent
            cancel_callback: Optional callback for cancellation

        Returns:
            Async iterator of processed chunks in requested format
        """
        # Reset normalizer state for new stream
        reset_method = getattr(self._normalizer, "reset", None)
        if callable(reset_method):
            try:
                reset_method()
            except Exception as exc:
                logger.debug(
                    "Failed to reset stream normalizer: %s", exc, exc_info=True
                )

        return self._normalizer.process_stream(
            response_iterator,
            output_format=output_format,
            cancel_callback=cancel_callback,
        )

    async def process_non_streaming(
        self,
        response: Any,
        session_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> ProcessedResponse:
        """Process a non-streaming response through the unified pipeline.

        The response is wrapped as a single-chunk stream, processed through
        all middleware, then unwrapped back to a single ProcessedResponse.

        Args:
            response: Complete response from backend
            session_id: Session identifier
            metadata: Additional metadata to pass through pipeline

        Returns:
            Processed response with all middleware applied
        """
        # Step 1: Wrap as single-chunk stream
        wrapped_stream = NonStreamingAdapter.wrap_as_stream(
            response, session_id, metadata
        )

        # Step 2: Reset normalizer state for clean processing
        reset_method = getattr(self._normalizer, "reset", None)
        if callable(reset_method):
            try:
                reset_method()
            except Exception as exc:
                logger.debug(
                    "Failed to reset stream normalizer: %s", exc, exc_info=True
                )

        # Step 3: Process through unified pipeline
        processed_stream = self._normalizer.process_stream(
            wrapped_stream,
            output_format="objects",
            cancel_callback=None,
        )

        # Step 4: Unwrap back to single response
        return await NonStreamingAdapter.unwrap_from_stream(processed_stream)
