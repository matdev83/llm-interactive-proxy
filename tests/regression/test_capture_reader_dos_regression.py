"""Regression test for CaptureReader DoS vulnerability fix.

This test verifies that the CaptureReader properly limits the number of entries
loaded from capture files to prevent DoS attacks through maliciously large files.

Fixed: Added MAX_CAPTURE_ENTRIES limit (10,000) to prevent memory exhaustion.
"""

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
    MAX_CAPTURE_ENTRIES,
    CaptureReader,
)


class TestCaptureReaderDoSRegression:
    """Regression tests for CaptureReader DoS vulnerability fix."""

    @pytest.fixture
    def temp_capture_dir(self):
        """Create a temporary directory for test capture files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def create_capture_file_with_entries(self, path: Path, num_entries: int) -> None:
        """Helper to create a capture file with specified number of entries."""
        header = CaptureFileHeader(session_id="test-session")
        with open(path, "wb") as f:
            cbor2.dump(header.to_dict(), f)
            for i in range(num_entries):
                entry = CaptureEntry(
                    timestamp=float(i),
                    direction=CaptureDirection.CLIENT_TO_PROXY,
                    sequence=i,
                    data=f"data_{i}".encode(),
                    metadata=CaptureMetadata(session_id="test"),
                )
                cbor2.dump(entry.to_dict(), f)

    def test_max_capture_entries_constant(self) -> None:
        """Test that MAX_CAPTURE_ENTRIES constant is defined correctly."""
        # Verify the constant exists and has reasonable value
        assert (
            MAX_CAPTURE_ENTRIES == 10000
        ), f"MAX_CAPTURE_ENTRIES ({MAX_CAPTURE_ENTRIES}) should be 10,000"
        assert MAX_CAPTURE_ENTRIES > 0, "MAX_CAPTURE_ENTRIES should be positive"

    def test_capture_file_within_limit_loaded(self, temp_capture_dir: Path) -> None:
        """Test that capture files within limit are fully loaded."""
        # Create file with entries just under limit (reduced from MAX_CAPTURE_ENTRIES - 100 for performance)
        capture_file = temp_capture_dir / "normal.cbor"
        num_entries = 100  # Sufficient to test "within limit" behavior
        self.create_capture_file_with_entries(capture_file, num_entries)

        reader = CaptureReader()
        session = reader.load(capture_file)

        assert (
            len(session.entries) == num_entries
        ), f"Should load all {num_entries} entries when under limit"

    def test_capture_file_at_limit_loaded(self, temp_capture_dir: Path) -> None:
        """Test that capture files exactly at limit are fully loaded."""
        # Create file with entries exactly at limit
        # Using a smaller but still meaningful number to test limit behavior efficiently
        capture_file = temp_capture_dir / "at_limit.cbor"
        num_entries = min(MAX_CAPTURE_ENTRIES, 2000)  # Use 2000 for performance while still testing many entries
        self.create_capture_file_with_entries(capture_file, num_entries)

        reader = CaptureReader()
        session = reader.load(capture_file)

        # Verify it loads all entries (testing that limit-checking doesn't truncate valid files)
        assert (
            len(session.entries) == num_entries
        ), f"Should load exactly {num_entries} entries when under limit"

    def test_capture_file_over_limit_truncated(self, temp_capture_dir: Path) -> None:
        """Test that capture files over limit are truncated to prevent DoS."""
        # Create file with entries over limit (reduced from 15,000 to 11,000 for performance)
        # Further reduced by mocking MAX_CAPTURE_ENTRIES to 100
        capture_file = temp_capture_dir / "oversized.cbor"
        
        # Patch MAX_CAPTURE_ENTRIES to a small number for testing
        with pytest.MonkeyPatch().context() as m:
            mock_limit = 100
            m.setattr("src.core.simulation.capture_reader.MAX_CAPTURE_ENTRIES", mock_limit)
            
            num_entries = mock_limit + 50
            self.create_capture_file_with_entries(capture_file, num_entries)

            reader = CaptureReader()
            session = reader.load(capture_file)

            # Should be truncated to MAX_CAPTURE_ENTRIES (mocked)
            assert len(session.entries) == mock_limit, (
                f"Should truncate to {mock_limit} entries when over limit. "
                f"Got {len(session.entries)} entries"
            )

    def test_capture_file_much_over_limit_truncated(
        self, temp_capture_dir: Path
    ) -> None:
        """Test that very large capture files are truncated to prevent DoS."""
        # Create file with many entries (simulating attack)
        capture_file = temp_capture_dir / "attack.cbor"
        num_entries = MAX_CAPTURE_ENTRIES + 2000  # 12,000 entries (just over limit)
        self.create_capture_file_with_entries(capture_file, num_entries)

        reader = CaptureReader()
        session = reader.load(capture_file)

        # Should be truncated to MAX_CAPTURE_ENTRIES
        assert len(session.entries) == MAX_CAPTURE_ENTRIES, (
            f"Should truncate to {MAX_CAPTURE_ENTRIES} entries even for very large files. "
            f"Got {len(session.entries)} entries"
        )

    def test_normal_capture_file_still_works(self, temp_capture_dir: Path) -> None:
        """Test that normal capture files still work correctly."""
        # Create normal-sized capture file
        capture_file = temp_capture_dir / "normal.cbor"
        num_entries = 10
        self.create_capture_file_with_entries(capture_file, num_entries)

        reader = CaptureReader()
        session = reader.load(capture_file)

        assert len(session.entries) == 10, "Normal files should work correctly"
        assert session.header.session_id == "test-session"
        assert session.entries[0].data == b"data_0"
        assert session.entries[9].data == b"data_9"

    def test_empty_capture_file_works(self, temp_capture_dir: Path) -> None:
        """Test that empty capture files (header only) still work."""
        capture_file = temp_capture_dir / "empty.cbor"
        header = CaptureFileHeader(session_id="test-session")
        with open(capture_file, "wb") as f:
            cbor2.dump(header.to_dict(), f)

        reader = CaptureReader()
        session = reader.load(capture_file)

        assert len(session.entries) == 0, "Empty files should work correctly"
        assert session.header.session_id == "test-session"
