"""Tests for CaptureReader."""

from __future__ import annotations

import tempfile
from pathlib import Path

import cbor2
import pytest
from src.core.domain.cbor_capture import (
    CaptureDirection,
    CaptureEntry,
    CaptureFileHeader,
    CaptureMetadata,
)
from src.core.simulation.capture_reader import (
    CaptureReader,
    CaptureReaderError,
    CaptureSummary,
    InvalidCaptureFileError,
)


@pytest.fixture
def temp_capture_dir():
    """Create a temporary directory for test capture files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def create_test_capture_file(path: Path, entries: list[CaptureEntry]) -> None:
    """Helper to create a test capture file."""
    header = CaptureFileHeader(session_id="test-session")
    with open(path, "wb") as f:
        cbor2.dump(header.to_dict(), f)
        for entry in entries:
            cbor2.dump(entry.to_dict(), f)


class TestCaptureReader:
    """Tests for CaptureReader class."""

    def test_load_valid_file(self, temp_capture_dir):
        """Test loading a valid capture file."""
        capture_file = temp_capture_dir / "test.cbor"
        entries = [
            CaptureEntry(
                timestamp=1.0,
                direction=CaptureDirection.CLIENT_TO_PROXY,
                sequence=0,
                data=b"request data",
                metadata=CaptureMetadata(session_id="test"),
            ),
            CaptureEntry(
                timestamp=2.0,
                direction=CaptureDirection.PROXY_TO_CLIENT,
                sequence=1,
                data=b"response data",
                metadata=CaptureMetadata(session_id="test"),
            ),
        ]
        create_test_capture_file(capture_file, entries)

        reader = CaptureReader()
        session = reader.load(capture_file)

        assert session.header.session_id == "test-session"
        assert len(session.entries) == 2
        assert session.entries[0].data == b"request data"
        assert session.entries[1].data == b"response data"

    def test_load_file_not_found(self, temp_capture_dir):
        """Test loading a non-existent file."""
        reader = CaptureReader()
        with pytest.raises(FileNotFoundError):
            reader.load(temp_capture_dir / "nonexistent.cbor")

    def test_load_invalid_magic(self, temp_capture_dir):
        """Test loading a file with invalid magic."""
        capture_file = temp_capture_dir / "invalid.cbor"
        with open(capture_file, "wb") as f:
            cbor2.dump({"magic": "WRONG", "version": 1}, f)

        reader = CaptureReader()
        with pytest.raises(
            InvalidCaptureFileError, match="Invalid capture file header"
        ):
            reader.load(capture_file)

    def test_load_corrupted_file(self, temp_capture_dir):
        """Test loading a corrupted file."""
        capture_file = temp_capture_dir / "corrupted.cbor"
        with open(capture_file, "wb") as f:
            f.write(b"not valid cbor data")

        reader = CaptureReader()
        with pytest.raises(CaptureReaderError):
            reader.load(capture_file)

    def test_get_session_without_load(self):
        """Test getting session without loading first."""
        reader = CaptureReader()
        with pytest.raises(RuntimeError, match="No capture session loaded"):
            reader.get_session()

    def test_get_client_sequence(self, temp_capture_dir):
        """Test filtering client-side entries."""
        capture_file = temp_capture_dir / "test.cbor"
        entries = [
            CaptureEntry(1.0, CaptureDirection.CLIENT_TO_PROXY, 0, b"req"),
            CaptureEntry(2.0, CaptureDirection.PROXY_TO_BACKEND, 1, b"be-req"),
            CaptureEntry(3.0, CaptureDirection.BACKEND_TO_PROXY, 2, b"be-resp"),
            CaptureEntry(4.0, CaptureDirection.PROXY_TO_CLIENT, 3, b"resp"),
        ]
        create_test_capture_file(capture_file, entries)

        reader = CaptureReader()
        reader.load(capture_file)

        client_entries = reader.get_client_sequence()
        assert len(client_entries) == 2
        assert client_entries[0].direction == CaptureDirection.CLIENT_TO_PROXY
        assert client_entries[1].direction == CaptureDirection.PROXY_TO_CLIENT

    def test_get_backend_sequence(self, temp_capture_dir):
        """Test filtering backend-side entries."""
        capture_file = temp_capture_dir / "test.cbor"
        entries = [
            CaptureEntry(1.0, CaptureDirection.CLIENT_TO_PROXY, 0, b"req"),
            CaptureEntry(2.0, CaptureDirection.PROXY_TO_BACKEND, 1, b"be-req"),
            CaptureEntry(3.0, CaptureDirection.BACKEND_TO_PROXY, 2, b"be-resp"),
            CaptureEntry(4.0, CaptureDirection.PROXY_TO_CLIENT, 3, b"resp"),
        ]
        create_test_capture_file(capture_file, entries)

        reader = CaptureReader()
        reader.load(capture_file)

        backend_entries = reader.get_backend_sequence()
        assert len(backend_entries) == 2
        assert backend_entries[0].direction == CaptureDirection.PROXY_TO_BACKEND
        assert backend_entries[1].direction == CaptureDirection.BACKEND_TO_PROXY

    def test_get_timing_deltas(self, temp_capture_dir):
        """Test computing timing deltas."""
        capture_file = temp_capture_dir / "test.cbor"
        entries = [
            CaptureEntry(1.0, CaptureDirection.CLIENT_TO_PROXY, 0, b"1"),
            CaptureEntry(1.5, CaptureDirection.PROXY_TO_BACKEND, 1, b"2"),
            CaptureEntry(2.5, CaptureDirection.BACKEND_TO_PROXY, 2, b"3"),
        ]
        create_test_capture_file(capture_file, entries)

        reader = CaptureReader()
        reader.load(capture_file)

        deltas = reader.get_timing_deltas()
        assert len(deltas) == 2
        assert abs(deltas[0] - 0.5) < 0.001
        assert abs(deltas[1] - 1.0) < 0.001

    def test_get_stream_chunks(self, temp_capture_dir):
        """Test extracting streaming chunks."""
        capture_file = temp_capture_dir / "test.cbor"
        entries = [
            # Stream 1
            CaptureEntry(
                1.0,
                CaptureDirection.BACKEND_TO_PROXY,
                0,
                b"",
                CaptureMetadata(is_stream_start=True),
            ),
            CaptureEntry(
                1.1,
                CaptureDirection.BACKEND_TO_PROXY,
                1,
                b"chunk1",
                CaptureMetadata(chunk_index=1),
            ),
            CaptureEntry(
                1.2,
                CaptureDirection.BACKEND_TO_PROXY,
                2,
                b"chunk2",
                CaptureMetadata(chunk_index=2),
            ),
            CaptureEntry(
                1.3,
                CaptureDirection.BACKEND_TO_PROXY,
                3,
                b"",
                CaptureMetadata(is_stream_end=True, total_chunks=2),
            ),
            # Stream 2
            CaptureEntry(
                2.0,
                CaptureDirection.BACKEND_TO_PROXY,
                4,
                b"",
                CaptureMetadata(is_stream_start=True),
            ),
            CaptureEntry(
                2.1,
                CaptureDirection.BACKEND_TO_PROXY,
                5,
                b"other",
                CaptureMetadata(chunk_index=1),
            ),
            CaptureEntry(
                2.2,
                CaptureDirection.BACKEND_TO_PROXY,
                6,
                b"",
                CaptureMetadata(is_stream_end=True, total_chunks=1),
            ),
        ]
        create_test_capture_file(capture_file, entries)

        reader = CaptureReader()
        reader.load(capture_file)

        streams = reader.get_stream_chunks(CaptureDirection.BACKEND_TO_PROXY)
        assert len(streams) == 2
        assert len(streams[0]) == 4  # start + 2 chunks + end
        assert len(streams[1]) == 3  # start + 1 chunk + end
        assert streams[0][1].data == b"chunk1"
        assert streams[0][2].data == b"chunk2"

    def test_summarize(self, temp_capture_dir):
        """Test capture summary generation."""
        capture_file = temp_capture_dir / "test.cbor"
        entries = [
            CaptureEntry(1.0, CaptureDirection.CLIENT_TO_PROXY, 0, b"req1"),
            CaptureEntry(1.5, CaptureDirection.PROXY_TO_BACKEND, 1, b"be-req1"),
            CaptureEntry(
                2.0,
                CaptureDirection.BACKEND_TO_PROXY,
                2,
                b"",
                CaptureMetadata(is_stream_start=True),
            ),
            CaptureEntry(
                2.1,
                CaptureDirection.BACKEND_TO_PROXY,
                3,
                b"chunk",
                CaptureMetadata(chunk_index=1),
            ),
            CaptureEntry(2.2, CaptureDirection.BACKEND_TO_PROXY, 4, b"chunk2"),
            CaptureEntry(3.0, CaptureDirection.PROXY_TO_CLIENT, 5, b"response"),
        ]
        create_test_capture_file(capture_file, entries)

        reader = CaptureReader()
        reader.load(capture_file)

        summary = reader.summarize()
        assert isinstance(summary, CaptureSummary)
        assert summary.session_id == "test-session"
        assert summary.total_entries == 6
        assert summary.direction_counts.client_to_proxy == 1
        assert summary.direction_counts.proxy_to_backend == 1
        assert summary.direction_counts.backend_to_proxy == 3
        assert summary.direction_counts.proxy_to_client == 1
        assert summary.stream_count == 1
        assert summary.duration_seconds == 2.0

    def test_inbound_outbound_filters(self, temp_capture_dir):
        """Test individual direction filters."""
        capture_file = temp_capture_dir / "test.cbor"
        entries = [
            CaptureEntry(1.0, CaptureDirection.CLIENT_TO_PROXY, 0, b"inbound-req"),
            CaptureEntry(2.0, CaptureDirection.PROXY_TO_BACKEND, 1, b"outbound-req"),
            CaptureEntry(3.0, CaptureDirection.BACKEND_TO_PROXY, 2, b"inbound-resp"),
            CaptureEntry(4.0, CaptureDirection.PROXY_TO_CLIENT, 3, b"outbound-resp"),
        ]
        create_test_capture_file(capture_file, entries)

        reader = CaptureReader()
        reader.load(capture_file)

        inbound_reqs = reader.get_inbound_requests()
        assert len(inbound_reqs) == 1
        assert inbound_reqs[0].data == b"inbound-req"

        outbound_reqs = reader.get_outbound_requests()
        assert len(outbound_reqs) == 1
        assert outbound_reqs[0].data == b"outbound-req"

        inbound_resps = reader.get_inbound_responses()
        assert len(inbound_resps) == 1
        assert inbound_resps[0].data == b"inbound-resp"

        outbound_resps = reader.get_outbound_responses()
        assert len(outbound_resps) == 1
        assert outbound_resps[0].data == b"outbound-resp"

    def test_empty_capture(self, temp_capture_dir):
        """Test loading an empty capture (header only)."""
        capture_file = temp_capture_dir / "empty.cbor"
        create_test_capture_file(capture_file, [])

        reader = CaptureReader()
        session = reader.load(capture_file)

        assert session.header.session_id == "test-session"
        assert len(session.entries) == 0
        assert reader.get_timing_deltas() == []
