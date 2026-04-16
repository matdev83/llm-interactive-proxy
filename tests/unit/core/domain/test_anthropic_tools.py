"""Tests for Anthropic tool definition helpers."""

import logging

import pytest
from src.core.domain.anthropic_tools import convert_anthropic_tool_to_openai


def test_flat_format_debug_logged_once_per_batch(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="src.core.domain.anthropic_tools")
    logged: set[object] = set()
    flat_tools = [
        {
            "name": f"tool_{i}",
            "description": "d",
            "input_schema": {"type": "object", "properties": {}},
        }
        for i in range(5)
    ]
    for t in flat_tools:
        convert_anthropic_tool_to_openai(t, _logged_flat_format=logged)

    flat_msgs = [
        r.message
        for r in caplog.records
        if r.message == "Identified as flat Anthropic tool format."
    ]
    assert len(flat_msgs) == 1
