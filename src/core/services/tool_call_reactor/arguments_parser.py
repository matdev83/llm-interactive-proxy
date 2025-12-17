"""
Tool arguments parser with JSON repair and safe telemetry.

This module implements argument parsing for the tool-call reactor subsystem,
extracting logic from the legacy middleware to support best-effort JSON repair
and safe telemetry recording without exposing secrets.
"""

from __future__ import annotations

import json
from typing import Any, Literal, Protocol

from json_repair import repair_json

from src.core.common.logging_utils import get_logger
from src.core.interfaces.tool_arguments_parser_interface import IToolArgumentsParser
from src.core.interfaces.tool_call_reactor_internal import (
    ToolArgumentsEnvelope,
    normalize_tool_arguments,
)

logger = get_logger(__name__)


class TelemetryRecorder(Protocol):
    """Protocol for recording tool argument repair outcomes.

    This protocol defines the interface for telemetry callbacks that record
    repair outcomes without exposing argument content (Requirement 12.1).
    """

    def record_tool_argument_repair_outcome(self, outcome: str) -> None:
        """Record a repair outcome.

        Args:
            outcome: The parse outcome ("success", "recovered", "failed").
                Only outcome strings are passed - never argument content.
        """
        ...


class ToolArgumentsParser(IToolArgumentsParser):
    """Parser for tool arguments with JSON repair and safe telemetry.

    This parser extracts the argument parsing logic from the legacy middleware,
    supporting best-effort JSON repair and safe telemetry recording. It never
    crashes - failed parsing results in a "failed" outcome with wrapped raw text.

    The parser uses the normalize_tool_arguments() helper for consistent
    normalization across the subsystem.
    """

    def __init__(
        self,
        telemetry_callback: TelemetryRecorder | None = None,
    ) -> None:
        """Initialize the parser.

        Args:
            telemetry_callback: Optional callback implementing TelemetryRecorder protocol
                for recording repair outcomes. Only outcome strings ("success", "recovered",
                "failed") are passed, never argument content (Requirement 12.1).
        """
        self._telemetry_callback = telemetry_callback

    def parse(self, raw_arguments: Any) -> ToolArgumentsEnvelope:
        """Parse tool arguments into a typed envelope.

        This method attempts to parse tool arguments following this strategy:
        1. If input is already a dict/list, normalize directly (outcome: "success")
        2. If input is a string, attempt JSON parsing with repair
        3. If repair succeeds, parse repaired JSON (outcome: "recovered")
        4. If all parsing fails, wrap raw text (outcome: "failed")

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
        """
        # Handle already-parsed types (dict, list) - use helper directly
        if isinstance(raw_arguments, dict | list):
            envelope = normalize_tool_arguments(raw_arguments)
            self._record_outcome(envelope.parse_outcome)
            return envelope

        # Handle string input - attempt parsing with repair
        if isinstance(raw_arguments, str):
            return self._parse_string(raw_arguments)

        # Handle other types - wrap as raw
        envelope = normalize_tool_arguments(raw_arguments)
        self._record_outcome(envelope.parse_outcome)
        return envelope

    def _parse_string(self, raw_arguments: str) -> ToolArgumentsEnvelope:
        """Parse a string input with JSON repair attempts.

        Args:
            raw_arguments: The raw argument string to parse.

        Returns:
            ToolArgumentsEnvelope with parse outcome and normalized arguments.
        """
        repair_outcome: Literal["success", "recovered", "failed"] = "failed"
        candidates: list[str] = []
        last_error: Exception | None = None

        # Attempt repair first
        try:
            repaired = repair_json(raw_arguments)
            if isinstance(repaired, str):
                candidates.append(repaired)
        except Exception:
            pass

        # Always include original as a candidate
        if raw_arguments not in candidates:
            candidates.append(raw_arguments)

        # Try parsing each candidate
        for candidate in candidates:
            try:
                # Try strict JSON parsing first
                parsed = json.loads(candidate)
                repair_outcome = "success"
                envelope = normalize_tool_arguments(
                    parsed, parse_outcome=repair_outcome
                )
                envelope.raw_arguments = raw_arguments
                self._record_outcome(repair_outcome)
                return envelope
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                last_error = exc
                try:
                    # Try relaxed parsing (allows some invalid JSON)
                    parsed_relaxed = json.loads(candidate, strict=False)
                    repair_outcome = "recovered"
                    envelope = normalize_tool_arguments(
                        parsed_relaxed, parse_outcome=repair_outcome
                    )
                    envelope.raw_arguments = raw_arguments
                    self._record_outcome(repair_outcome)
                    return envelope
                except (json.JSONDecodeError, TypeError, ValueError) as relaxed_exc:
                    last_error = relaxed_exc
                    continue

        # All parsing attempts failed - wrap raw text
        if last_error is not None:
            logger.warning(
                "Could not parse tool arguments after repair attempts: %s",
                last_error,
                exc_info=True,
            )
        else:
            logger.warning("Could not parse tool arguments after repair attempts")

        envelope = normalize_tool_arguments(raw_arguments, parse_outcome=repair_outcome)
        self._record_outcome(repair_outcome)
        return envelope

    def _record_outcome(
        self, outcome: Literal["success", "recovered", "failed"]
    ) -> None:
        """Record repair outcome via telemetry callback if available.

        Args:
            outcome: The parse outcome ("success", "recovered", "failed").
                Only outcome strings are passed - never argument content (Requirement 12.1).
        """
        if self._telemetry_callback is None:
            return

        recorder = getattr(
            self._telemetry_callback, "record_tool_argument_repair_outcome", None
        )
        if callable(recorder):
            try:
                recorder(outcome)
            except Exception as e:
                # Don't fail parsing if telemetry fails
                logger.debug("Failed to record repair outcome: %s", e, exc_info=True)
