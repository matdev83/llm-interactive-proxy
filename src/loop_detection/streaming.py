"""
Streaming response utilities for loop detection integration.

This module provides wrappers and utilities for integrating loop detection
with streaming responses from LLM backends.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from starlette.responses import StreamingResponse

from .detector import LoopDetectionEvent, LoopDetector

logger = logging.getLogger(__name__)


class LoopDetectionStreamingResponse(StreamingResponse):
    """Streaming response wrapper that integrates loop detection."""

    def __init__(
        self,
        content: AsyncIterator[Any],
        loop_detector: LoopDetector | None = None,
        on_loop_detected: Callable[[LoopDetectionEvent], None] | None = None,
        cancel_upstream: Callable[[], Awaitable[None]] | None = None,
        **kwargs: Any,
    ):
        self.loop_detector = loop_detector
        self.on_loop_detected = on_loop_detected
        self.cancel_upstream = cancel_upstream
        self._cancelled = False

        # Wrap the content iterator with loop detection
        if loop_detector and loop_detector.is_enabled():
            content = self._wrap_content_with_detection(content)

        super().__init__(content, **kwargs)

    async def _wrap_content_with_detection(
        self, content: AsyncIterator[Any]
    ) -> AsyncIterator[Any]:
        """Wrap content iterator to include loop detection."""
        # Buffer for aggregating small chunks to reduce analysis overhead
        chunk_buffer = ""
        min_chunk_size = 64  # Minimum size before processing

        try:
            async for chunk in content:
                # Check if we've been cancelled
                if self._cancelled:
                    logger.info("Streaming response cancelled due to loop detection")
                    break

                # Process chunk for loop detection
                if isinstance(chunk, str | bytes):
                    chunk_text = (
                        chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
                    )

                    # Aggregate small chunks to reduce analysis overhead
                    chunk_buffer += chunk_text
                    if len(chunk_buffer) < min_chunk_size:
                        # Yield the original chunk and continue buffering
                        yield chunk
                        continue

                    # Process the buffered content
                    # If loop_detector is None, it means it's not enabled, and this method
                    # should not have been called to wrap the content.
                    # Adding assert to satisfy type checker.
                    assert self.loop_detector is not None
                    detection_event = self.loop_detector.process_chunk(chunk_buffer)
                    chunk_buffer = ""  # Clear buffer after processing

                    if detection_event:
                        logger.warning(
                            f"Loop detected in streaming response: {detection_event.pattern[:50]}..."
                        )
                        self._trigger_callback_safely(detection_event)
                        self._cancelled = True
                        # Best-effort upstream cancellation: try to close the
                        # underlying async iterator if supported to stop token burn.
                        # Also call the provided cancel_upstream callable if available.
                        try:
                            if self.cancel_upstream:
                                await self.cancel_upstream()
                            aclose = getattr(content, "aclose", None)
                            if callable(aclose):
                                await aclose()  # type: ignore[misc]
                        except Exception:
                            # Swallow errors from upstream close attempts
                            pass
                        yield self._create_cancellation_message(detection_event)
                        break

                # Yield the original chunk
                yield chunk

            # Process any remaining buffered content
            if not self._cancelled and chunk_buffer:
                assert self.loop_detector is not None
                detection_event = self.loop_detector.process_chunk(chunk_buffer)
                if detection_event:
                    logger.warning(
                        f"Loop detected in streaming response (end of stream): {detection_event.pattern[:50]}..."
                    )
                    self._trigger_callback_safely(detection_event)
                    self._cancelled = True
                    yield self._create_cancellation_message(detection_event)

        except asyncio.CancelledError:
            logger.info("Streaming response cancelled")
            raise
        except Exception as e:
            logger.error(f"Error in loop detection streaming wrapper: {e}")
            # Continue streaming on error to avoid breaking the response
            async for chunk in content:
                yield chunk

    def _trigger_callback_safely(self, detection_event: LoopDetectionEvent) -> None:
        """Invoke the callback safely if provided."""
        if not self.on_loop_detected:
            return
        try:
            self.on_loop_detected(detection_event)
        except Exception as e:
            logger.error(f"Error in loop detection callback: {e}")

    def _create_cancellation_message(
        self, detection_event: LoopDetectionEvent
    ) -> str | None:
        """Create a cancellation message to send when a loop is detected."""
        # Emit an SSE-compatible line so that OpenAI/Gemini style clients that
        # parse incremental JSON do not choke on raw text.  The payload is a
        # simple string wrapped in an SSE "data:" envelope followed by the
        # mandatory blank line.

        payload = (
            f"[Response cancelled: Loop detected - Pattern "
            f"'{detection_event.pattern[:30]}...' repeated "
            f"{detection_event.repetition_count} times]"
        )
        return f"data: {payload}\n\n"

    def cancel(self) -> None:
        """Cancel the streaming response."""
        self._cancelled = True


async def wrap_streaming_content_with_loop_detection(
    content: AsyncIterator[Any],
    loop_detector: LoopDetector | None = None,
    on_loop_detected: Callable[[LoopDetectionEvent], None] | None = None,
    cancel_upstream: Callable[[], Awaitable[None]] | None = None,
) -> AsyncIterator[Any]:
    """
    Wrap streaming content with loop detection.

    This is a standalone function that can be used to wrap any async iterator
    with loop detection capabilities.
    """
    # Simply delegate to the LoopDetectionStreamingResponse class
    # The class handles all the complexity of wrapping and loop detection.
    response_wrapper = LoopDetectionStreamingResponse(
        content=content,
        loop_detector=loop_detector,
        on_loop_detected=on_loop_detected,
        cancel_upstream=cancel_upstream,
    )
    # The _wrap_content_with_detection method of the class already returns an async iterator
    # that handles the streaming logic.
    async for chunk in response_wrapper._wrap_content_with_detection(content):
        yield chunk


def _detect_simple_repetition(text: str) -> tuple[str | None, int]:
    """Naive fallback: detect short substring repeated consecutively at least 3 times.

    Looks for 1-6 char token repeated; returns (pattern, count) or (None, 0).
    """
    try:
        # Fast path: common noisy token
        token = "ERROR "
        if token in text:
            count = text.count(token)
            return (token.strip(), count)

        # Generic short-pattern repetition
        max_token_len = 6
        for size in range(1, max_token_len + 1):
            for i in range(min(len(text), 256) - size * 3 + 1):
                candidate = text[i : i + size]
                if not candidate.strip():
                    continue
                repeats = 1
                j = i + size
                while j + size <= len(text) and text[j : j + size] == candidate:
                    repeats += 1
                    j += size
                if repeats >= 3:
                    return (candidate, repeats)
        return (None, 0)
    except Exception:
        return (None, 0)


def analyze_complete_response_for_loops(
    response_text: str, loop_detector: LoopDetector | None = None
) -> LoopDetectionEvent | None:
    """
    Analyze a complete response for loops (for non-streaming responses).

    Args:
        response_text: The complete response text to analyze
        loop_detector: The loop detector instance to use

    Returns:
        LoopDetectionEvent if a loop is detected, None otherwise
    """
    if not loop_detector or not loop_detector.is_enabled():
        return None

    # Reset detector state for fresh analysis
    loop_detector.reset()

    # Process the entire response as a single chunk
    return loop_detector.process_chunk(response_text)
