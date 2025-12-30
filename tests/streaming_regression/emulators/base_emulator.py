"""Base emulator for streaming backends."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from time import perf_counter as _perf_counter
from typing import Any

from src.connectors.base import LLMBackend
from src.core.config.app_config import AppConfig
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.domain.session_key import SessionKey
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.model_bases import DomainModel, InternalDTO
from src.core.interfaces.response_processor_interface import ProcessedResponse


class StreamingEmulatorBase(LLMBackend):
    """Base class for streaming backend emulators.

    Emulators simulate realistic streaming behavior:
    - Send chunks incrementally with delays
    - Track timing for regression detection
    - Support various content types
    """

    backend_type: str = "emulator"

    def __init__(
        self,
        chunks: Sequence[str | bytes | dict[str, Any]],
        chunk_delay: float = 0.01,
        config: AppConfig | None = None,
    ) -> None:
        """Initialize emulator.

        Args:
            chunks: List of chunks to stream
            chunk_delay: Delay between chunks in seconds
            config: Optional config (creates test config if not provided)
        """
        if config is None:
            from src.core.app.test_builder import create_test_config

            config = create_test_config()
        super().__init__(config=config)
        self.chunks = list(chunks)
        self.chunk_delay = chunk_delay
        self.chunk_timestamps: list[float] = []
        self.chunks_sent = 0

    async def chat_completions(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        processed_messages: list[Any],
        effective_model: str,
        identity: IAppIdentityConfig | None = None,
        cancellation_token: SessionKey | None = None,
        cancellation_coordinator: Any | None = None,
        **kwargs: Any,
    ) -> StreamingResponseEnvelope:
        """Simulate streaming chat completion."""
        stream = getattr(request_data, "stream", False)

        if not stream:
            # Non-streaming not implemented for emulators
            raise NotImplementedError("Emulators only support streaming mode")

        async def stream_generator() -> AsyncIterator[ProcessedResponse]:
            """Generate chunks with realistic delays."""
            self.chunk_timestamps.clear()
            self.chunks_sent = 0

            for chunk in self.chunks:
                # Always yield control to event loop to simulate streaming
                # Even with chunk_delay=0, use a small delay to ensure separate async yields
                # and consistent timing for regression detection
                delay = self.chunk_delay if self.chunk_delay > 0 else 0.02
                await asyncio.sleep(delay)

                # Record timestamp after delay, right before yielding
                # This reflects when chunks are actually sent, not when they're queued
                self.chunk_timestamps.append(_perf_counter())

                # Convert to ProcessedResponse
                if isinstance(chunk, bytes):
                    content: Any = chunk.decode("utf-8")
                else:
                    content = chunk

                # Safe debug print
                content_preview = str(content)[:50] if content else ""
                print(f"DEBUG: Emulator yielding chunk: {content_preview!r}")
                self.chunks_sent += 1
                yield ProcessedResponse(content=content)

        return StreamingResponseEnvelope(
            content=stream_generator(),
            media_type="text/event-stream",
            headers={"content-type": "text/event-stream"},
        )

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize emulator (no-op)."""

    def get_available_models(self) -> list[str]:
        """Return test model list."""
        return ["test-model"]

    def get_timing_stats(self) -> dict[str, Any]:
        """Get timing statistics for regression detection.

        Returns:
            Dictionary with timing metrics:
            - chunks_sent: Number of chunks sent
            - timestamps: List of chunk timestamps
            - min_delay: Minimum delay between chunks
            - max_delay: Maximum delay between chunks
            - avg_delay: Average delay between chunks
            - all_at_once: Whether all chunks arrived within 1ms (buffering detected)
        """
        if len(self.chunk_timestamps) < 2:
            return {
                "chunks_sent": self.chunks_sent,
                "timestamps": self.chunk_timestamps,
                "min_delay": 0,
                "max_delay": 0,
                "avg_delay": 0,
                "all_at_once": False,
            }

        delays = [
            self.chunk_timestamps[i + 1] - self.chunk_timestamps[i]
            for i in range(len(self.chunk_timestamps) - 1)
        ]

        return {
            "chunks_sent": self.chunks_sent,
            "timestamps": self.chunk_timestamps,
            "min_delay": min(delays),
            "max_delay": max(delays),
            "avg_delay": sum(delays) / len(delays),
            "all_at_once": max(delays)
            < 0.01,  # All within 10ms = buffered (accounts for asyncio.sleep(0) overhead)
        }
