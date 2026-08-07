"""
Pytest fixtures for simulation-based testing.

Provides fixtures for creating capture files, running simulations,
and validating responses against captured expectations.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import cbor2
import pytest
import pytest_asyncio
from src.core.domain.cbor_capture import (
    CaptureDirection,
    CaptureEntry,
    CaptureFileHeader,
    CaptureMetadata,
)
from src.core.simulation import (
    BackendSimulator,
    CaptureReader,
    ClientSimulator,
    SimulationRunner,
    TimingController,
)


@pytest.fixture
def temp_capture_dir():
    """Create a temporary directory for capture files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def capture_reader():
    """Provide a CaptureReader instance."""
    return CaptureReader()


@pytest.fixture
def timing_controller():
    """Provide a TimingController with realtime speed."""
    return TimingController(speed_multiplier=1.0)


@pytest.fixture
def fast_timing_controller():
    """Provide a TimingController with fast speed for testing."""
    return TimingController(speed_multiplier=10.0, max_delay=0.1)


@pytest.fixture
def simulation_runner():
    """Provide a SimulationRunner instance."""
    return SimulationRunner(
        proxy_base_url="http://localhost:8000",
        timing_tolerance_ms=100.0,
        speed_multiplier=10.0,  # Fast for testing
    )


def create_capture_file(
    path: Path,
    entries: list[CaptureEntry],
    session_id: str = "test-session",
    metadata: dict[str, Any] | None = None,
) -> None:
    """Helper to create a capture file for testing.

    Args:
        path: Path to write the capture file
        entries: List of capture entries
        session_id: Session ID for the capture
        metadata: Optional metadata dict
    """
    header = CaptureFileHeader(
        session_id=session_id,
        metadata=metadata or {},
    )
    with open(path, "wb") as f:
        cbor2.dump(header.to_dict(), f)
        for entry in entries:
            cbor2.dump(entry.to_dict(), f)


def create_simple_request_response(
    request_data: bytes,
    response_data: bytes,
    session_id: str = "test",
    start_time: float = 1.0,
) -> list[CaptureEntry]:
    """Create a simple request/response pair for testing.

    Args:
        request_data: Request body bytes
        response_data: Response body bytes
        session_id: Session ID
        start_time: Starting timestamp

    Returns:
        List of capture entries
    """
    return [
        CaptureEntry(
            timestamp=start_time,
            direction=CaptureDirection.CLIENT_TO_PROXY,
            sequence=0,
            data=request_data,
            metadata=CaptureMetadata(session_id=session_id),
        ),
        CaptureEntry(
            timestamp=start_time + 0.1,
            direction=CaptureDirection.PROXY_TO_BACKEND,
            sequence=1,
            data=request_data,
            metadata=CaptureMetadata(session_id=session_id, backend="test"),
        ),
        CaptureEntry(
            timestamp=start_time + 0.2,
            direction=CaptureDirection.BACKEND_TO_PROXY,
            sequence=2,
            data=response_data,
            metadata=CaptureMetadata(session_id=session_id, backend="test"),
        ),
        CaptureEntry(
            timestamp=start_time + 0.3,
            direction=CaptureDirection.PROXY_TO_CLIENT,
            sequence=3,
            data=response_data,
            metadata=CaptureMetadata(session_id=session_id),
        ),
    ]


def create_streaming_response(
    request_data: bytes,
    chunks: list[bytes],
    session_id: str = "test",
    start_time: float = 1.0,
    chunk_delay: float = 0.1,
) -> list[CaptureEntry]:
    """Create a streaming request/response for testing.

    Args:
        request_data: Request body bytes
        chunks: List of response chunk bytes
        session_id: Session ID
        start_time: Starting timestamp
        chunk_delay: Delay between chunks

    Returns:
        List of capture entries
    """
    entries = [
        CaptureEntry(
            timestamp=start_time,
            direction=CaptureDirection.CLIENT_TO_PROXY,
            sequence=0,
            data=request_data,
            metadata=CaptureMetadata(session_id=session_id),
        ),
        CaptureEntry(
            timestamp=start_time + 0.1,
            direction=CaptureDirection.PROXY_TO_BACKEND,
            sequence=1,
            data=request_data,
            metadata=CaptureMetadata(session_id=session_id, backend="test"),
        ),
        # Stream start from backend
        CaptureEntry(
            timestamp=start_time + 0.2,
            direction=CaptureDirection.BACKEND_TO_PROXY,
            sequence=2,
            data=b"",
            metadata=CaptureMetadata(
                session_id=session_id, backend="test", is_stream_start=True
            ),
        ),
    ]

    # Add chunks
    for i, chunk in enumerate(chunks):
        entries.append(
            CaptureEntry(
                timestamp=start_time + 0.2 + (i + 1) * chunk_delay,
                direction=CaptureDirection.BACKEND_TO_PROXY,
                sequence=3 + i,
                data=chunk,
                metadata=CaptureMetadata(
                    session_id=session_id, backend="test", chunk_index=i + 1
                ),
            )
        )

    # Stream end from backend
    entries.append(
        CaptureEntry(
            timestamp=start_time + 0.2 + (len(chunks) + 1) * chunk_delay,
            direction=CaptureDirection.BACKEND_TO_PROXY,
            sequence=3 + len(chunks),
            data=b"",
            metadata=CaptureMetadata(
                session_id=session_id,
                backend="test",
                is_stream_end=True,
                total_chunks=len(chunks),
                total_bytes=sum(len(c) for c in chunks),
            ),
        )
    )

    # Stream to client
    entries.append(
        CaptureEntry(
            timestamp=start_time + 0.3 + (len(chunks) + 1) * chunk_delay,
            direction=CaptureDirection.PROXY_TO_CLIENT,
            sequence=4 + len(chunks),
            data=b"",
            metadata=CaptureMetadata(session_id=session_id, is_stream_start=True),
        )
    )

    for i, chunk in enumerate(chunks):
        entries.append(
            CaptureEntry(
                timestamp=start_time + 0.3 + (len(chunks) + 2 + i) * chunk_delay,
                direction=CaptureDirection.PROXY_TO_CLIENT,
                sequence=5 + len(chunks) + i,
                data=chunk,
                metadata=CaptureMetadata(session_id=session_id, chunk_index=i + 1),
            )
        )

    entries.append(
        CaptureEntry(
            timestamp=start_time + 0.3 + (2 * len(chunks) + 2) * chunk_delay,
            direction=CaptureDirection.PROXY_TO_CLIENT,
            sequence=5 + 2 * len(chunks),
            data=b"",
            metadata=CaptureMetadata(
                session_id=session_id,
                is_stream_end=True,
                total_chunks=len(chunks),
            ),
        )
    )

    return entries


@pytest.fixture
def simple_capture_file(temp_capture_dir):
    """Create a simple capture file with request/response pair."""
    path = temp_capture_dir / "simple.cbor"
    entries = create_simple_request_response(
        request_data=b'{"model": "test", "messages": []}',
        response_data=b'{"choices": [{"message": {"content": "Hello"}}]}',
    )
    create_capture_file(path, entries)
    return path


@pytest.fixture
def streaming_capture_file(temp_capture_dir):
    """Create a capture file with streaming response."""
    path = temp_capture_dir / "streaming.cbor"
    entries = create_streaming_response(
        request_data=b'{"model": "test", "messages": [], "stream": true}',
        chunks=[
            b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n',
            b'data: {"choices":[{"delta":{"content":" world"}}]}\n\n',
            b'data: {"choices":[{"delta":{"content":"!"}}]}\n\n',
            b"data: [DONE]\n\n",
        ],
    )
    create_capture_file(path, entries)
    return path


@pytest_asyncio.fixture
async def backend_simulator(temp_capture_dir):
    """Create a BackendSimulator with a test capture."""
    path = temp_capture_dir / "backend_test.cbor"
    entries = create_simple_request_response(
        request_data=b'{"test": "request"}',
        response_data=b'{"test": "response"}',
    )
    create_capture_file(path, entries)

    reader = CaptureReader()
    session = reader.load(path)
    return BackendSimulator(session)


@pytest_asyncio.fixture
async def client_simulator_fixture(temp_capture_dir):
    """Create a ClientSimulator with a test capture.

    This fixture returns a simulator that must be used as an async context manager:
        async with client_simulator_fixture as simulator:
            await simulator.replay_request(...)
    """
    path = temp_capture_dir / "client_test.cbor"
    entries = create_simple_request_response(
        request_data=b'{"test": "request"}',
        response_data=b'{"test": "response"}',
    )
    create_capture_file(path, entries)

    reader = CaptureReader()
    session = reader.load(path)
    return ClientSimulator(session)


# Export helper functions for use in tests
__all__ = [
    "create_capture_file",
    "create_simple_request_response",
    "create_streaming_response",
]
