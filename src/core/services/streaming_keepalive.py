"""Streaming keep-alive generator for SSE connections.

This module provides utilities to generate keep-alive chunks during wait periods
to prevent client/connection timeouts.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncGenerator

from pydantic.types import JsonValue

from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.streaming.processed_stream_idle_keepalive import (
    wrap_processed_stream_with_idle_keepalive,
)

logger = logging.getLogger(__name__)


def _keepalive_processed_response(
    *,
    completion_id: str,
    model: str,
    session_id: str | None,
    stream_id: str | None,
) -> ProcessedResponse:
    created = int(time.time())
    metadata: dict[str, JsonValue] = {
        "_keepalive": True,
        "id": completion_id,
        "model": model,
        "created": created,
    }
    if session_id:
        metadata["session_id"] = session_id
    if stream_id:
        metadata["stream_id"] = stream_id
    return ProcessedResponse(content="", metadata=metadata)


async def generate_keepalive_chunks(
    interval_seconds: float = 8.0,
    total_duration: float = 30.0,
    *,
    completion_id: str = "chatcmpl-keepalive",
    model: str = "keepalive",
    session_id: str | None = None,
    stream_id: str | None = None,
) -> AsyncGenerator[ProcessedResponse, None]:
    """Generate SSE keep-alive comments at regular intervals.

    This generator yields keep-alive chunks that keep streaming connections alive
    during wait periods without sending actual content to the client.

    Args:
        interval_seconds: Seconds between keep-alive comments.
        total_duration: Maximum total duration to generate keep-alives.
        completion_id: OpenAI-style completion id to attach to chunks.
        model: Model name to attach to chunks.
        session_id: Session id to attach in metadata (not sent to client).
        stream_id: Stream id to attach in metadata (not sent to client).

    Yields:
        ProcessedResponse chunks that will be serialized to SSE downstream.
    """
    elapsed = 0.0

    if total_duration > 0:
        logger.debug("Emitting keep-alive chunk (elapsed: %.1fs)", elapsed)
        yield _keepalive_processed_response(
            completion_id=completion_id,
            model=model,
            session_id=session_id,
            stream_id=stream_id,
        )

    while elapsed < total_duration:
        await asyncio.sleep(interval_seconds)
        elapsed += interval_seconds

        if elapsed <= total_duration:
            logger.debug("Emitting keep-alive chunk (elapsed: %.1fs)", elapsed)
            yield _keepalive_processed_response(
                completion_id=completion_id,
                model=model,
                session_id=session_id,
                stream_id=stream_id,
            )


async def generate_keepalive_with_status(
    wait_seconds: float,
    interval_seconds: float = 8.0,
    *,
    completion_id: str = "chatcmpl-keepalive",
    model: str = "keepalive",
    session_id: str | None = None,
    stream_id: str | None = None,
) -> AsyncGenerator[ProcessedResponse, None]:
    """Generate SSE keep-alive comments with status information.

    Similar to generate_keepalive_chunks but includes periodic emissions during a wait.

    Args:
        wait_seconds: Total seconds to wait.
        interval_seconds: Seconds between keep-alive comments.
        completion_id: OpenAI-style completion id to attach to chunks.
        model: Model name to attach to chunks.
        session_id: Session id to attach in metadata (not sent to client).
        stream_id: Stream id to attach in metadata (not sent to client).

    Yields:
        ProcessedResponse chunks that will be serialized to SSE downstream.
    """
    elapsed = 0.0

    if wait_seconds > 0:
        remaining = max(0.0, wait_seconds - elapsed)
        logger.debug("Emitting status keep-alive (remaining: %.1fs)", remaining)
        yield _keepalive_processed_response(
            completion_id=completion_id,
            model=model,
            session_id=session_id,
            stream_id=stream_id,
        )

    while elapsed < wait_seconds:
        await asyncio.sleep(min(interval_seconds, wait_seconds - elapsed))
        elapsed += interval_seconds

        remaining = max(0.0, wait_seconds - elapsed)
        logger.debug("Emitting status keep-alive (remaining: %.1fs)", remaining)
        yield _keepalive_processed_response(
            completion_id=completion_id,
            model=model,
            session_id=session_id,
            stream_id=stream_id,
        )


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
        *,
        model: str = "keepalive",
        session_id: str | None = None,
        stream_id: str | None = None,
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
        self._model = model
        self._session_id = session_id
        self._stream_id = stream_id
        self._completion_id = f"chatcmpl-keepalive-{uuid.uuid4().hex}"
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

    async def __aiter__(self) -> AsyncGenerator[ProcessedResponse, None]:
        """Async iterate over keep-alive chunks."""
        if self._started:
            return
        self._started = True

        try:
            if self._include_status:
                async for chunk in generate_keepalive_with_status(
                    self._wait_seconds,
                    self._interval_seconds,
                    completion_id=self._completion_id,
                    model=self._model,
                    session_id=self._session_id,
                    stream_id=self._stream_id,
                ):
                    yield chunk
            else:
                async for chunk in generate_keepalive_chunks(
                    self._interval_seconds,
                    self._wait_seconds,
                    completion_id=self._completion_id,
                    model=self._model,
                    session_id=self._session_id,
                    stream_id=self._stream_id,
                ):
                    yield chunk
        finally:
            self._completed = True


__all__ = [
    "generate_keepalive_chunks",
    "generate_keepalive_with_status",
    "KeepAliveGenerator",
    "wrap_processed_stream_with_idle_keepalive",
]
