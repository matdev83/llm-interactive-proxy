from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolCallRepairResult:
    """Result of a tool call repair operation."""

    tool_call: dict[str, Any]
    snippet: str


class IToolCallRepairService(ABC):
    """Interface for repairing tool calls in LLM responses."""

    @abstractmethod
    def repair_tool_calls(
        self,
        response_content: str,
        force_reprocess: bool = False,
        allowed_tools: list[str] | None = None,
    ) -> ToolCallRepairResult | None:
        """Detects tool calls within the given response content and converts
        them into an OpenAI-compatible tool_calls structure.

        Args:
            response_content: The string content of the LLM response.
            force_reprocess: If True, reprocess even if already processed.
            allowed_tools: Optional list of tool names to restrict detection to.

        Returns:
            A ToolCallRepairResult containing the parsed tool call and the original
            text snippet if a tool call is detected, otherwise None.
        """
