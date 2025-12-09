"""Streaming keep-alive generator for SSE connections.

This module provides utilities to generate SSE keep-alive comments
during wait periods to prevent client/connection timeouts.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)

# Standard SSE keep-alive comment format
# A colon followed by optional text and double newline is an SSE comment
# that clients should ignore but will reset connection timeouts
KEEPALIVE_COMMENT = b": keepalive\n\n"


async def generate_keepalive_chunks(
    interval_seconds: float = 8.0,
    total_duration: float = 30.0,
) -> AsyncGenerator[bytes, None]:
    """Generate SSE keep-alive comments at regular intervals.

    This generator yields SSE comment chunks that keep streaming connections
    alive during wait periods without sending actual content to the client.

    Args:
        interval_seconds: Seconds between keep-alive comments.
        total_duration: Maximum total duration to generate keep-alives.

    Yields:
        SSE comment bytes (b': keepalive\\n\\n').
    """
    elapsed = 0.0

    while elapsed < total_duration:
        await asyncio.sleep(interval_seconds)
        elapsed += interval_seconds

        if elapsed <= total_duration:
            logger.debug("Emitting keep-alive comment (elapsed: %.1fs)", elapsed)
            yield KEEPALIVE_COMMENT


async def generate_keepalive_with_status(
    wait_seconds: float,
    interval_seconds: float = 8.0,
) -> AsyncGenerator[bytes, None]:
    """Generate SSE keep-alive comments with status information.

    Similar to generate_keepalive_chunks but includes status hints
    in the comments showing time remaining.

    Args:
        wait_seconds: Total seconds to wait.
        interval_seconds: Seconds between keep-alive comments.

    Yields:
        SSE comment bytes with status information.
    """
    elapsed = 0.0

    while elapsed < wait_seconds:
        await asyncio.sleep(min(interval_seconds, wait_seconds - elapsed))
        elapsed += interval_seconds

        remaining = max(0, wait_seconds - elapsed)
        if remaining > 0:
            comment = f": retrying in {remaining:.0f}s\n\n".encode()
            logger.debug("Emitting status keep-alive (remaining: %.1fs)", remaining)
            yield comment
        else:
            yield b": retrying now\n\n"


class KeepAliveGenerator:
    """Helper class for generating keep-alive chunks in a retry context.

    This class manages keep-alive generation during a wait-and-retry
    operation, tracking state and providing clean async iteration.
    """

    def __init__(
        self,
        wait_seconds: float,
        interval_seconds: float = 8.0,
        include_status: bool = False,
    ):
        """Initialize the keep-alive generator.

        Args:
            wait_seconds: Total seconds to wait while generating keep-alives.
            interval_seconds: Seconds between keep-alive comments.
            include_status: Whether to include retry status in comments.
        """
        self._wait_seconds = wait_seconds
        self._interval_seconds = interval_seconds
        self._include_status = include_status
        self._started = False
        self._completed = False

    @property
    def wait_seconds(self) -> float:
        """Total wait duration in seconds."""
        return self._wait_seconds

    @property
    def completed(self) -> bool:
        """Whether the wait period has completed."""
        return self._completed

    async def __aiter__(self) -> AsyncGenerator[bytes, None]:
        """Async iterate over keep-alive chunks."""
        if self._started:
            return
        self._started = True

        try:
            if self._include_status:
                async for chunk in generate_keepalive_with_status(
                    self._wait_seconds, self._interval_seconds
                ):
                    yield chunk
            else:
                async for chunk in generate_keepalive_chunks(
                    self._interval_seconds, self._wait_seconds
                ):
                    yield chunk
        finally:
            self._completed = True


__all__ = [
    "KEEPALIVE_COMMENT",
    "generate_keepalive_chunks",
    "generate_keepalive_with_status",
    "KeepAliveGenerator",
]
