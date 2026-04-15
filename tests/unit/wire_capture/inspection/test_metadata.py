"""Unit tests for capture inspection metadata helpers."""

from __future__ import annotations

import pytest
from src.core.wire_capture.inspection.metadata import validate_capture_header


def test_validate_capture_header_rejects_wrong_version() -> None:
    with pytest.raises(ValueError, match="Unsupported capture file version"):
        validate_capture_header(
            {
                "magic": "LLMPROXY-CAPTURE-V2",
                "version": 1,
            }
        )
