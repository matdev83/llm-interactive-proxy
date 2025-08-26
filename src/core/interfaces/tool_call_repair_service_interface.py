from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class IToolCallRepairService(ABC):
    """Interface for repairing tool calls in LLM responses."""

    @abstractmethod
    def repair_tool_calls(self, response_content: str) -> dict[str, Any] | None:
        """Detects tool calls within the given response content and converts
        them into an OpenAI-compatible tool_calls structure.

        Args:
            response_content: The string content of the LLM response.

        Returns:
            A dictionary representing the OpenAI-compatible tool_calls structure
            if a tool call is detected and successfully parsed, otherwise None.
        """
