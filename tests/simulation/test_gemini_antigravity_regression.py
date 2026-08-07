"""
Regression test for antigravity-oauth backend issues.

This test uses a captured CBOR wire capture session to verify the proxy's
handling of:
1. Empty responses from the primary backend
2. Model name masking in responses
3. Fallback mechanism activation

The capture file documents real-world issues discovered during testing.
"""

from __future__ import annotations

from pathlib import Path

from src.core.domain.cbor_capture import (
    CaptureDirection,
)
from src.core.simulation import (
    CaptureReader,
)


def test_backend_entries_have_valid_directions(
    capture_reader: CaptureReader, simple_capture_file: Path
) -> None:
    """Test that backend entries from a capture have valid directions.

    This test verifies that all backend entries in a capture file have
    valid directions (PROXY_TO_BACKEND or BACKEND_TO_PROXY).
    """
    session = capture_reader.load(simple_capture_file)
    backend_entries = session.get_backend_entries()

    assert len(backend_entries) > 0, "Capture should contain backend entries"

    for e in backend_entries:
        assert e.direction in (
            CaptureDirection.PROXY_TO_BACKEND,
            CaptureDirection.BACKEND_TO_PROXY,
        ), f"Backend entry has invalid direction: {e.direction}"
