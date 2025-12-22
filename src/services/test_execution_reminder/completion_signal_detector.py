"""Completion signal detection for test execution reminder system."""

from __future__ import annotations

from typing import Any


class CompletionSignalDetector:
    """Detects completion signals in tool calls.

    This detector identifies when agents signal task completion through:
    1. Explicit completion tool calls (e.g., attempt_completion from Cline/Roo-Code)

    The detector uses actual tool names from popular coding agents rather than
    speculative pattern matching, making it reliable and accurate.
    """

    # Tool names that signal completion
    # These are actual tool names used by popular coding agents:
    # - attempt_completion: Used by Cline, Roo-Code (Kilo Code)
    # - finish: Used by OpenHands (formerly OpenDevin)
    # - finish_task: Generic completion tool
    # - task_complete: Generic completion tool
    # - mark_complete: Generic completion tool
    COMPLETION_TOOLS = {
        "attempt_completion",  # Cline, Roo-Code (most common)
        "finish",  # OpenHands (formerly OpenDevin)
        "finish_task",
        "task_complete",
        "mark_complete",
        "complete",
        "done",
    }

    @classmethod
    def is_completion_tool(cls, tool_name: str) -> bool:
        """Check if tool name indicates completion.

        Performs case-insensitive matching with normalization to handle
        variations in tool naming conventions (underscores, hyphens, etc.).

        Args:
            tool_name: The name of the tool to check

        Returns:
            True if the tool name indicates completion, False otherwise
        """
        if not tool_name:
            return False

        # Normalize the input tool name: lowercase, remove underscores and hyphens
        normalized_input = tool_name.lower().replace("_", "").replace("-", "")

        # Check against all completion tool patterns with the same normalization
        for pattern in cls.COMPLETION_TOOLS:
            normalized_pattern = pattern.replace("_", "").replace("-", "")
            if normalized_input == normalized_pattern:
                return True

        return False

