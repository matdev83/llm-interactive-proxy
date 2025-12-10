"""Tool call loop detection mode enum.

This module is kept minimal to avoid circular import issues.
Both src.tool_call_loop.config and src.core.domain.configuration.loop_detection_config
import from this module.
"""

from __future__ import annotations

from enum import Enum


class ToolLoopMode(str, Enum):
    """Mode of operation for tool call loop detection."""

    BREAK = "break"
    CHANCE_THEN_BREAK = "chance_then_break"
