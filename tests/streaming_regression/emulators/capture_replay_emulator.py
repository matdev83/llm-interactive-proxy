"""Capture replay emulator for streaming backends."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from src.core.config.app_config import AppConfig
from src.core.domain.cbor_capture import CaptureDirection, CaptureEntry
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.domain.session_key import SessionKey
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.model_bases import DomainModel, InternalDTO
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.simulation.capture_reader import CaptureReader
from src.core.simulation.timing_controller import TimingController

from .base_emulator import StreamingEmulatorBase


class CaptureReplayEmulator(StreamingEmulatorBase):
    """Emulator that replays chunks from a CBOR capture file.

    This emulator:
    - Loads captured traffic from a CBOR file
    - Replays backend responses with original timing
    - Supports both streaming and non-streaming responses
    - Tracks timing for regression detection
    """

    backend_type: str = "capture_replay"

    def __init__(
        self,
        capture_path: Path | str,
        direction_filter: CaptureDirection = CaptureDirection.BACKEND_TO_PROXY,
        speed_multiplier: float = 1.0,
        config: AppConfig | None = None,
    ) -> None:
        """Initialize capture replay emulator.

        Args:
            capture_path: Path to the CBOR capture file
            direction_filter: Direction of entries to replay
            speed_multiplier: Speed multiplier for replay timing
            config: Optional config
        """
        # Load capture
        reader = CaptureReader()
        self._session = reader.load(Path(capture_path))
        self._direction_filter = direction_filter
        self._speed_multiplier = speed_multiplier
        self._timing = TimingController(speed_multiplier=speed_multiplier)

        # Extract chunks from capture
        chunks = self._extract_chunks()

        # Initialize base with extracted chunks
        super().__init__(chunks=chunks, chunk_delay=0, config=config)

        # Store original entries for timing
        self._response_entries = self._get_response_entries()

    def _extract_chunks(self) -> list[bytes]:
        """Extract chunk data from capture entries."""
        chunks: list[bytes] = []
        for entry in self._session.entries:
            if (
                entry.direction == self._direction_filter
                and entry.data
                and not entry.metadata.is_stream_start
            ):
                chunks.append(entry.data)
        return chunks

    def _get_response_entries(self) -> list[CaptureEntry]:
        """Get response entries with data for timing."""
        return [
            entry
            for entry in self._session.entries
            if entry.direction == self._direction_filter
            and entry.data
            and not entry.metadata.is_stream_start
        ]

    @classmethod
    def from_capture_file(
        cls,
        path: Path | str,
        speed_multiplier: float = 1.0,
        config: AppConfig | None = None,
    ) -> CaptureReplayEmulator:
        """Create emulator from a capture file.

        Args:
            path: Path to the CBOR capture file
            speed_multiplier: Speed multiplier for replay
            config: Optional config

        Returns:
            CaptureReplayEmulator instance
        """
        return cls(
            capture_path=path,
            direction_filter=CaptureDirection.BACKEND_TO_PROXY,
            speed_multiplier=speed_multiplier,
            config=config,
        )

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
        """Replay captured streaming response with timing."""
        stream = getattr(request_data, "stream", False)

        if not stream and self._response_entries:
            # Non-streaming: return concatenated response
            all_data = b"".join(e.data for e in self._response_entries)

            # This should return a ResponseEnvelope, but for compatibility
            # we return a streaming envelope with single chunk
            async def single_response() -> AsyncIterator[ProcessedResponse]:
                yield ProcessedResponse(
                    content=all_data.decode("utf-8", errors="replace")
                )

            return StreamingResponseEnvelope(
                content=single_response(),
                media_type="application/json",
                headers={"content-type": "application/json"},
            )

        # Streaming response with original timing
        async def stream_generator() -> AsyncIterator[ProcessedResponse]:
            """Generate chunks with captured timing."""
            self.chunk_timestamps.clear()
            self.chunks_sent = 0

            if not self._response_entries:
                return

            # Start timing from first entry
            self._timing.start(self._response_entries[0].timestamp)

            for entry in self._response_entries:
                # Wait for appropriate timing
                await self._timing.wait_for_entry(entry.timestamp)

                # Record timestamp
                self.chunk_timestamps.append(time.time())

                # Convert to ProcessedResponse
                content = entry.data.decode("utf-8", errors="replace")
                self.chunks_sent += 1

                yield ProcessedResponse(content=content)

        return StreamingResponseEnvelope(
            content=stream_generator(),
            media_type="text/event-stream",
            headers={"content-type": "text/event-stream"},
        )

    def get_capture_summary(self) -> dict[str, Any]:
        """Get summary of the loaded capture.

        Returns:
            Dictionary with capture metadata and statistics
        """
        return {
            "session_id": self._session.header.session_id,
            "total_entries": len(self._session.entries),
            "response_entries": len(self._response_entries),
            "total_bytes": sum(len(e.data) for e in self._response_entries),
            "direction_filter": self._direction_filter.name,
            "speed_multiplier": self._speed_multiplier,
        }

    def get_original_timing(self) -> list[float]:
        """Get original timing deltas from capture.

        Returns:
            List of time deltas between entries in the capture
        """
        if len(self._response_entries) < 2:
            return []
        return [
            self._response_entries[i + 1].timestamp
            - self._response_entries[i].timestamp
            for i in range(len(self._response_entries) - 1)
        ]

    def compare_timing(self) -> dict[str, Any]:
        """Compare actual replay timing with original capture timing.

        Returns:
            Dictionary with timing comparison metrics
        """
        original = self.get_original_timing()
        actual_stats = self.get_timing_stats()

        if not original or len(self.chunk_timestamps) < 2:
            return {
                "comparison_available": False,
                "original_delays": original,
                "actual_stats": actual_stats,
            }

        actual = [
            self.chunk_timestamps[i + 1] - self.chunk_timestamps[i]
            for i in range(len(self.chunk_timestamps) - 1)
        ]

        # Calculate deviations
        min_len = min(len(original), len(actual))
        deviations = [
            abs(actual[i] - original[i] / self._speed_multiplier)
            for i in range(min_len)
        ]

        return {
            "comparison_available": True,
            "original_avg_delay": sum(original) / len(original) if original else 0,
            "actual_avg_delay": sum(actual) / len(actual) if actual else 0,
            "avg_deviation": sum(deviations) / len(deviations) if deviations else 0,
            "max_deviation": max(deviations) if deviations else 0,
            "timing_preserved": all(d < 0.05 for d in deviations),  # Within 50ms
        }
