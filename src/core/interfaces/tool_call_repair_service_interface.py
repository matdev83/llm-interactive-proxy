from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class IToolCallRepairService(ABC):
    """Interface for repairing tool calls in LLM responses."""

    @abstractmethod
    def repair_tool_calls(
        self,
        response_content: str,
        force_reprocess: bool = False,
        allowed_tools: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Detects tool calls within the given response content and converts
        them into an OpenAI-compatible tool_calls structure.

        Args:
            response_content: The string content of the LLM response.
            force_reprocess: If True, reprocess even if already processed.
            allowed_tools: Optional list of tool names to restrict detection to.

        Returns:
            A dictionary representing the OpenAI-compatible tool_calls structure
            if a tool call is detected and successfully parsed, otherwise None.
        """
