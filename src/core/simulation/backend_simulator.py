"""
Backend simulator for replay-based testing.

Provides a mock HTTP server that replays captured backend responses
with accurate timing.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from src.core.domain.cbor_capture import CaptureDirection, CaptureEntry, CaptureSession
from src.core.domain.simulation import SimulatorStatistics
from src.core.simulation.timing_controller import TimingController

logger = logging.getLogger(__name__)


@dataclass
class RequestMatch:
    """Result of matching an incoming request to a captured request."""

    matched: bool
    captured_request: CaptureEntry | None = None
    response_entries: list[CaptureEntry] = field(default_factory=list)
    is_streaming: bool = False


class BackendSimulator:
    """Mock HTTP server that replays captured backend responses.

    This simulator:
    - Matches incoming requests to captured request patterns
    - Responds with exact captured bytes
    - Maintains original timing for streaming responses
    - Supports both streaming and non-streaming responses
    """

    def __init__(
        self,
        session: CaptureSession,
        timing_controller: TimingController | None = None,
    ) -> None:
        """Initialize the backend simulator.

        Args:
            session: The capture session to replay
            timing_controller: Optional timing controller for delay management
        """
        self._session = session
        self._timing = timing_controller or TimingController()
        self._request_index = 0
        self._response_queues: dict[int, list[CaptureEntry]] = {}
        self._prepare_responses()

    def _prepare_responses(self) -> None:
        """Prepare response queues from capture entries."""
        entries = self._session.entries

        # Find all outbound requests to backend and their responses
        current_request_idx = -1
        for i, entry in enumerate(entries):
            if entry.direction == CaptureDirection.PROXY_TO_BACKEND:
                # This is a request to the backend
                if (
                    not entry.metadata.is_stream_start
                    and entry.metadata.chunk_index is None
                ):
                    current_request_idx = i
                    self._response_queues[current_request_idx] = []
            elif (
                entry.direction == CaptureDirection.BACKEND_TO_PROXY
                and current_request_idx >= 0
            ):
                # This is a response from the backend
                self._response_queues[current_request_idx].append(entry)

    def match_request(self, request_data: bytes) -> RequestMatch:
        """Match an incoming request to a captured request.

        Uses a simple sequential matching strategy - each request is matched
        to the next unmatched captured request.

        Args:
            request_data: The raw request bytes

        Returns:
            RequestMatch with response entries if matched
        """
        entries = self._session.entries

        # Find the next unmatched request
        request_indices = sorted(self._response_queues.keys())
        if self._request_index >= len(request_indices):
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("No more captured requests to match")
            return RequestMatch(matched=False)

        req_idx = request_indices[self._request_index]
        self._request_index += 1

        captured_request = entries[req_idx]
        response_entries = self._response_queues[req_idx]

        # Check if this is a streaming response
        is_streaming = any(e.metadata.is_stream_start for e in response_entries)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"Matched request {self._request_index} to captured request at index {req_idx}, "
                f"streaming={is_streaming}, responses={len(response_entries)}"
            )

        return RequestMatch(
            matched=True,
            captured_request=captured_request,
            response_entries=response_entries,
            is_streaming=is_streaming,
        )

    async def get_response(self, request_data: bytes) -> bytes:
        """Get the response for a request (non-streaming).

        Args:
            request_data: The raw request bytes

        Returns:
            The response bytes

        Raises:
            ValueError: If no matching response found
        """
        match = self.match_request(request_data)
        if not match.matched or not match.response_entries:
            raise ValueError("No matching response for request")

        if match.is_streaming:
            # For streaming responses, concatenate all chunks
            chunks = [
                e.data
                for e in match.response_entries
                if e.data
                and not e.metadata.is_stream_start
                and not e.metadata.is_stream_end
            ]
            return b"".join(chunks)
        else:
            # Non-streaming: return first response
            return match.response_entries[0].data

    async def stream_response(self, request_data: bytes) -> AsyncIterator[bytes]:
        """Stream the response for a request with timing.

        Args:
            request_data: The raw request bytes

        Yields:
            Response chunks with original timing

        Raises:
            ValueError: If no matching response found
        """
        match = self.match_request(request_data)
        if not match.matched or not match.response_entries:
            raise ValueError("No matching response for request")

        # Start timing from first response entry
        if match.response_entries:
            self._timing.start(match.response_entries[0].timestamp)

        for entry in match.response_entries:
            # Skip stream markers with empty data
            if (
                entry.metadata.is_stream_start or entry.metadata.is_stream_end
            ) and not entry.data:
                continue

            # Wait for appropriate timing
            await self._timing.wait_for_entry(entry.timestamp)

            # Yield the chunk
            if entry.data:
                yield entry.data

    def get_remaining_request_count(self) -> int:
        """Get the number of remaining unmatched requests.

        Returns:
            Number of requests not yet matched
        """
        return len(self._response_queues) - self._request_index

    def reset(self) -> None:
        """Reset the simulator to replay from the beginning."""
        self._request_index = 0
        self._timing.reset()

    def get_statistics(self) -> SimulatorStatistics:
        """Get replay statistics.

        Returns:
            SimulatorStatistics with replay stats
        """
        total_requests = len(self._response_queues)
        matched_requests = self._request_index
        streaming_responses = sum(
            1
            for entries in self._response_queues.values()
            if any(e.metadata.is_stream_start for e in entries)
        )

        return SimulatorStatistics(
            total_requests=total_requests,
            matched_requests=matched_requests,
            remaining_requests=total_requests - matched_requests,
            streaming_responses=streaming_responses,
            elapsed_time=self._timing.get_elapsed_time(),
        )



class BackendSimulatorTransport:
    """HTTPX transport adapter for BackendSimulator.

    Allows using BackendSimulator with httpx.AsyncClient for integration testing.
    """

    def __init__(self, simulator: BackendSimulator) -> None:
        """Initialize the transport.

        Args:
            simulator: The backend simulator to use
        """
        self._simulator = simulator

    async def handle_async_request(self, request: Any) -> Any:
        """Handle an async request using the simulator.

        Args:
            request: The httpx Request object

        Returns:
            An httpx Response object
        """
        import httpx

        # Read request body
        request_data = request.content if hasattr(request, "content") else b""
        if hasattr(request_data, "read"):
            request_data = await request_data.read()

        match = self._simulator.match_request(request_data)
        if not match.matched:
            return httpx.Response(
                status_code=404,
                content=b'{"error": "No matching captured request"}',
                headers={"content-type": "application/json"},
            )

        if match.is_streaming:
            # For streaming, collect all chunks with timing
            chunks: list[bytes] = []
            async for chunk in self._simulator.stream_response(request_data):
                chunks.append(chunk)
            return httpx.Response(
                status_code=200,
                content=b"".join(chunks),
                headers={"content-type": "text/event-stream"},
            )
        else:
            # Return non-streaming response
            response_data = await self._simulator.get_response(request_data)
            return httpx.Response(
                status_code=200,
                content=response_data,
                headers={"content-type": "application/json"},
            )
