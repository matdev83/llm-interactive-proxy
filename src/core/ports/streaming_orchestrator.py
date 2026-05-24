"""
Streaming pipeline orchestrator.

This module provides the orchestration layer that coordinates the flow
from backend → normalizer → processor chain → assembler.

This is the missing piece that wires together all the streaming infrastructure
components into a cohesive pipeline.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import AsyncIterator, MutableMapping
from contextlib import AsyncExitStack, suppress
from typing import Any

from cachetools import TTLCache  # type: ignore

from src.core.common.exceptions import LLMProxyError
from src.core.ports.sse_assembler import SSEAssembler
from src.core.ports.streaming.interfaces import IProviderStreamNormalizer
from src.core.ports.streaming_contracts import (
    IStreamAssembler,
    IStreamNormalizer,
    IStreamProcessor,
    StreamingContent,
)
from src.core.ports.streaming_metrics import get_metrics_instance

logger = logging.getLogger(__name__)

# Multiple ``process_stream`` async generators may run for the same logical
# ``stream_id`` (e.g. shared session id). On client disconnect each one
# receives ``GeneratorExit`` and would emit identical DEBUG lines; collapse
# bursts per (provider, stream_id) for a short TTL.
_client_disconnect_debug_lock = threading.Lock()
_client_disconnect_debug_recent: MutableMapping[str, bool] = TTLCache(
    maxsize=10_000, ttl=2.0
)


def _emit_client_disconnect_debug(provider: str, stream_id: str) -> None:
    """Log client disconnect at DEBUG at most once per provider/stream burst."""
    if not stream_id or not logger.isEnabledFor(logging.DEBUG):
        return
    key = f"{provider}\n{stream_id}"
    with _client_disconnect_debug_lock:
        if key in _client_disconnect_debug_recent:
            return
        _client_disconnect_debug_recent[key] = True
    logger.debug(
        "Client disconnected during streaming",
        extra={"provider": provider, "stream_id": stream_id},
    )


async def safe_aclose(
    stream: Any,
    provider: str | None = None,
    stream_id: str | None = None,
    *,
    timeout_s: float = 5.0,
) -> None:
    """Close stream, tolerating errors during GeneratorExit cleanup.

    Important: closing an async generator may hang indefinitely if the underlying
    transport/SDK blocks during shutdown. Since `safe_aclose()` is invoked from
    request/response cleanup paths, we must never block forever here.

    Args:
        stream: The stream object (usually an async generator).
        provider: Optional provider name for logging context.
        stream_id: Optional stream identifier for logging context.
        timeout_s: Max seconds to wait for `aclose()` to finish before giving up.
    """

    if stream is None:
        return

    try:
        if not hasattr(stream, "aclose"):
            return

        res = stream.aclose()

        # Use shield to ensure aclose() finishes even if this task is cancelled.
        # This is critical for nested async generators where multiple callbacks
        # may attempt to close the same underlying stream sequentially.
        if asyncio.iscoroutine(res):
            try:
                task = asyncio.create_task(res)
            except RuntimeError as err:
                if "no running event loop" in str(err):
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Skipping stream aclose; no running event loop",
                            extra={"provider": provider, "stream_id": stream_id},
                        )
                    return
                raise
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=timeout_s)
            except asyncio.TimeoutError:
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await task
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Timed out waiting for stream aclose()",
                        extra={"provider": provider, "stream_id": stream_id},
                    )
                return
            except asyncio.CancelledError:
                with suppress(asyncio.CancelledError, Exception):
                    await asyncio.shield(task)
                raise
        elif res is not None:
            await asyncio.wait_for(res, timeout=timeout_s)

    except (RuntimeError, GeneratorExit, asyncio.CancelledError) as err:
        # Happens when aclose() is invoked while the generator is mid-execution
        # or already closing.
        err_str = str(err)
        if (
            isinstance(err, RuntimeError)
            and (
                "aclose(): asynchronous generator is already running" in err_str
                or "async generator ignored GeneratorExit" in err_str
            )
        ) or isinstance(err, GeneratorExit | asyncio.CancelledError):
            if stream_id and logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Skipping stream aclose; generator already closing or ignored exit",
                    extra={
                        "provider": provider,
                        "stream_id": stream_id,
                        "error": err_str,
                    },
                )
            return
        raise


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
        yield_interval: int = 100,
    ) -> None:
        """Initialize the streaming pipeline.

        Args:
            normalizer: The normalizer for converting backend chunks
            processors: Optional list of middleware processors
            assembler: Optional assembler for output formatting (defaults to SSE)
            yield_interval: Number of chunks to batch before yielding to event loop
        """
        self.normalizer = normalizer
        self.processors = processors or []
        self.assembler = assembler or SSEAssembler(yield_interval=yield_interval)
        self._metrics = get_metrics_instance()
        self._yield_interval = yield_interval

    async def process_stream(
        self,
        raw_stream: AsyncIterator[object],
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
            raw_stream: Raw async iterator from backend (opaque provider-specific data)
            provider: Provider name for context
            stream_id: Optional stream identifier
            output_format: Output format (default: "sse")

        Yields:
            Formatted bytes ready for client transmission
        """
        # Start metrics tracking
        if stream_id:
            self._metrics.start_stream(stream_id)

        # Keep references to intermediate generators for proper cleanup
        normalized_stream: AsyncIterator[StreamingContent] | None = None
        processed_stream: AsyncIterator[StreamingContent] | None = None
        assembled_stream: AsyncIterator[bytes] | None = None

        try:
            async with AsyncExitStack() as stack:
                # Register raw stream cleanup first (will be cleaned up last)
                if hasattr(raw_stream, "aclose"):
                    stack.push_async_callback(
                        safe_aclose, raw_stream, provider, stream_id
                    )

                # Step 1: Normalize backend chunks to StreamingContent
                normalized_stream = self.normalizer.normalize_stream(
                    raw_stream, provider
                )
                # Register cleanup for normalized stream
                stack.push_async_callback(
                    safe_aclose, normalized_stream, provider, stream_id
                )

                # Step 2: Apply processor chain
                processed_stream = self._apply_processor_chain(
                    normalized_stream, stream_id
                )
                # Register cleanup for processed stream
                stack.push_async_callback(
                    safe_aclose, processed_stream, provider, stream_id
                )

                # Step 3: Assemble to client format
                assembled_stream = self.assembler.assemble_stream(
                    processed_stream, output_format
                )
                # Register cleanup for assembled stream
                stack.push_async_callback(
                    safe_aclose, assembled_stream, provider, stream_id
                )

                # Step 4: Yield formatted bytes
                try:
                    async for chunk_bytes in assembled_stream:
                        yield chunk_bytes
                except GeneratorExit:
                    # Client disconnected - this is expected behavior
                    # Don't try to process this in the outer exception handler
                    # as it will interfere with the context manager cleanup
                    _emit_client_disconnect_debug(provider, stream_id or "")
                    raise

        except GeneratorExit:
            # Re-raise GeneratorExit to allow proper cleanup without logging errors
            raise
        except LLMProxyError as e:
            # Domain error (e.g. RateLimitExceededError) - log at lower level without stack trace.
            # These are expected backend errors being propagated through the pipeline.
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Domain error in streaming pipeline",
                    extra={
                        "provider": provider,
                        "stream_id": stream_id,
                        "error": str(e),
                        "error_type": type(e).__name__,
                    },
                )
            if stream_id:
                # Still increment error metrics as it's a failed stream
                self._metrics.increment_error_terminations(stream_id)
            raise
        except Exception as e:
            # Unexpected pipeline bug or catastrophic failure - log as ERROR with stack trace.
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
    normalizer: IProviderStreamNormalizer | None = None,
    yield_interval: int = 100,
) -> StreamingPipeline:
    """Factory function to create a pipeline for a specific provider.

    This function creates a complete pipeline with the specified processors.
    The normalizer must be provided explicitly (requirement 5.2 - no implicit construction).

    Args:
        provider: Provider name ("openai", "anthropic", "gemini", etc.) - used for validation/logging
        processors: Optional list of middleware processors
        normalizer: Provider normalizer instance (required)
        yield_interval: Number of chunks to batch before yielding to event loop

    Returns:
        Configured StreamingPipeline instance

    Raises:
        ValueError: If normalizer is not provided or provider is not supported
    """
    if normalizer is None:
        raise ValueError(
            f"Normalizer is required for provider '{provider}'. "
            "Provider normalizers must be constructed explicitly at the call site."
        )

    # Create and return pipeline
    return StreamingPipeline(
        normalizer=normalizer,
        processors=processors,
        yield_interval=yield_interval,
    )
