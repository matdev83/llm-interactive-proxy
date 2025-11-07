"""Shared types for the hybrid connector implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.core.interfaces.response_processor_interface import ProcessedResponse


@dataclass
class ReasoningPhaseResult:
    """Container for reasoning phase outcome."""

    text: str
    complete: bool
    tool_calls: list[dict[str, Any]]
    raw_chunks: list[ProcessedResponse]
    media_type: str | None
    headers: dict[str, str] | None

    def has_tool_calls(self) -> bool:
        """Check whether reasoning produced any tool calls."""

        return bool(self.tool_calls)
