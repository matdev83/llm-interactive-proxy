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

import pytest

from src.core.simulation import (
    CaptureReader,
)
from src.core.domain.cbor_capture import (
    CaptureDirection,
    CaptureSession,
)


def test_backend_entries_have_valid_directions(capture_reader: CaptureReader) -> None:
    """Test that backend entries from a capture have valid directions."""
    # TODO: Add capture file path when available
    # For now, this test structure is in place
    # Example usage:
    # capture_path = Path("var/wire_captures_cbor/antigravity_session.cbor")
    # session = capture_reader.load(capture_path)
    # backend_entries = session.get_backend_entries()
    # for e in backend_entries:
    #     assert e.direction in (
    #         CaptureDirection.PROXY_TO_BACKEND,
    #         CaptureDirection.BACKEND_TO_PROXY,
    #     )
    pass
