"""
Interface for tool arguments parsing in the tool-call reactor subsystem.

This module defines the interface for components that parse tool arguments
with JSON repair and safe telemetry recording.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.core.interfaces.tool_call_reactor_internal import ToolArgumentsEnvelope


class IToolArgumentsParser(ABC):
    """Interface for parsing tool arguments with repair and telemetry.

    This parser attempts to parse tool arguments from various input shapes
    (string, dict, list) and returns a ToolArgumentsEnvelope with parsing
    outcomes. It supports best-effort JSON repair for invalid JSON and
    records repair outcomes via safe telemetry (no secrets logged).

    The parser never crashes - it returns a "failed" outcome with wrapped
    raw text when parsing cannot succeed.
    """

    @abstractmethod
    def parse(self, raw_arguments: Any) -> ToolArgumentsEnvelope:
        """Parse tool arguments into a typed envelope.

        This method attempts to parse tool arguments following this strategy:
        1. If input is already a dict/list, normalize directly (outcome: "success")
        2. If input is a string, attempt JSON parsing
        3. If JSON parsing fails, attempt repair via json_repair
        4. If repair succeeds, parse repaired JSON (outcome: "recovered")
        5. If all parsing fails, wrap raw text (outcome: "failed")

        Args:
            raw_arguments: The raw tool arguments. Can be:
                - A dictionary (already parsed JSON object)
                - A list (already parsed JSON array)
                - A string (may be JSON string or raw text)
                - Other types (wrapped as raw)

        Returns:
            ToolArgumentsEnvelope with normalized arguments and parse outcome.
            The envelope always contains normalized_arguments (never None),
            even when parsing fails (wrapped in reserved keys).

        Note:
            This method should not raise exceptions. If parsing fails,
            it returns an envelope with parse_outcome="failed" and
            normalized_arguments containing wrapped raw text.
        """
        ...
