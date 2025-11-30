"""Completion signal detection for test execution reminder system."""

from __future__ import annotations

from typing import Any


class CompletionSignalDetector:
    """Detects completion signals in tool calls and streaming responses.

    This detector identifies when agents signal task completion through:
    1. Explicit completion tool calls (e.g., attempt_completion from Cline/Roo-Code)
    2. Streaming finish_reason markers (e.g., "stop", "tool_calls", "length")

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

    # Finish reasons that indicate end of streaming response
    # These are standard finish_reason values from OpenAI/Anthropic APIs:
    # - stop: Normal completion
    # - tool_calls: Completed with tool calls
    # - length: Max tokens reached
    # - end_turn: Anthropic's completion marker
    FINISH_REASONS = {
        "stop",
        "tool_calls",
        "length",
        "end_turn",
    }

    @classmethod
    def is_completion_signal(
        cls,
        tool_name: str | None = None,
        tool_arguments: dict[str, Any] | None = None,
        finish_reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Check if this represents a completion signal.

        This method checks for completion signals in two reliable ways:
        1. Tool name matches known completion tools (e.g., attempt_completion)
        2. Streaming finish_reason indicates end of response

        Args:
            tool_name: The name of the tool being invoked (if any)
            tool_arguments: The arguments passed to the tool (currently unused)
            finish_reason: The finish_reason from streaming response (if any)
            metadata: Additional metadata that may contain finish_reason

        Returns:
            True if this represents a completion signal, False otherwise

        Examples:
            >>> CompletionSignalDetector.is_completion_signal(
            ...     tool_name="attempt_completion"
            ... )
            True
            >>> CompletionSignalDetector.is_completion_signal(
            ...     finish_reason="stop"
            ... )
            True
            >>> CompletionSignalDetector.is_completion_signal(
            ...     tool_name="write_file"
            ... )
            False
        """
        # Priority 1: Check if tool name indicates completion
        # This is the most reliable signal - agents explicitly call completion tools
        if tool_name and cls._is_completion_tool(tool_name):
            return True

        # Priority 2: Check if finish_reason indicates end of streaming response
        # This catches the end of the LLM's response stream
        if finish_reason and cls._is_finish_reason(finish_reason):
            return True

        # Also check metadata for finish_reason
        if metadata and isinstance(metadata, dict):
            meta_finish_reason = metadata.get("finish_reason")
            if meta_finish_reason and cls._is_finish_reason(meta_finish_reason):
                return True

        return False

    @classmethod
    def _is_completion_tool(cls, tool_name: str) -> bool:
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

    @classmethod
    def _is_finish_reason(cls, finish_reason: str) -> bool:
        """Check if finish_reason indicates end of response.

        Performs case-insensitive matching against known finish_reason values
        from OpenAI, Anthropic, and other LLM APIs.

        Args:
            finish_reason: The finish_reason value to check

        Returns:
            True if the finish_reason indicates completion, False otherwise
        """
        if not finish_reason:
            return False

        # Normalize and check against known finish reasons
        normalized = finish_reason.strip().lower()
        return normalized in cls.FINISH_REASONS
