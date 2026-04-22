"""Tests for Anthropic SSE error status mapping."""

from __future__ import annotations

import pytest
from src.connectors.anthropic import _anthropic_stream_error_status


@pytest.mark.parametrize(
    ("error_type", "expected_status"),
    [
        ("invalid_request_error", 400),
        ("authentication_error", 401),
        ("permission_error", 403),
        ("not_found_error", 404),
        ("rate_limit_error", 429),
        ("overloaded_error", 529),
        ("unknown", 500),
    ],
)
def test_anthropic_stream_error_status_mapping(
    error_type: str,
    expected_status: int,
) -> None:
    assert _anthropic_stream_error_status(error_type) == expected_status
