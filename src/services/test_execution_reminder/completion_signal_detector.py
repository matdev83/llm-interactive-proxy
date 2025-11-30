"""Completion signal detection for test execution reminder system."""

from __future__ import annotations

import re
from typing import Any


class CompletionSignalDetector:
    """Detects completion signals in tool calls and messages.

    This detector identifies when agents signal task completion through
    either explicit tool calls or message patterns. It uses regex pattern
    matching to distinguish genuine completion signals from progress updates
    or ambiguous messages.
    """

    # Patterns that indicate task completion
    # These patterns are designed to match genuine completion signals while
    # avoiding false positives from progress updates or ambiguous messages.
    COMPLETION_PATTERNS = [
        # Pattern 1: "(task|implementation|feature|fix|change)(s)? (is )?(complete|done|finished|ready)"
        # Matches: "task is complete", "changes are done", "feature finished"
        # Avoids: "need to complete", "will be done"
        re.compile(
            r"\b(task|implementation|feature|fix|changes?)\s+(is\s+|are\s+)?(complete|done|finished|ready)\b",
            re.IGNORECASE,
        ),
        # Pattern 2: "completed? (the )?(task|implementation|feature|fix|work)"
        # Matches: "completed the task", "complete work"
        # Avoids: "need to complete the task", "will complete the work"
        # Use negative lookbehind to avoid matching after "to" or "will"
        re.compile(
            r"(?<!to\s)(?<!will\s)\bcompleted?\s+(the\s+)?(task|implementation|feature|fix|work)\b",
            re.IGNORECASE,
        ),
        # Pattern 3: "all (tests?|checks?) pass(ing|ed)?"
        # Matches: "all tests pass", "all checks passed"
        re.compile(
            r"\ball\s+(tests?|checks?)\s+pass(ing|ed)?\b",
            re.IGNORECASE,
        ),
        # Pattern 4: "ready (for|to) (review|merge|deploy|commit)"
        # Matches: "ready for review", "ready to merge"
        re.compile(
            r"\bready\s+(for|to)\s+(review|merge|deploy|commit)\b",
            re.IGNORECASE,
        ),
        # Pattern 5: "finished (implementing|coding|working on)"
        # Matches: "finished implementing", "finished coding"
        re.compile(
            r"\bfinished\s+(implementing|coding|working\s+on)\b",
            re.IGNORECASE,
        ),
    ]

    # Tool names that signal completion
    COMPLETION_TOOLS = {
        "task_complete",
        "mark_complete",
        "finish_task",
        "complete",
        "done",
    }

    @classmethod
    def is_completion_signal(
        cls,
        tool_name: str,
        tool_arguments: dict[str, Any] | None = None,
        response_text: str | None = None,
    ) -> bool:
        """Check if this represents a completion signal.

        This method checks both the tool name and any response text for
        completion indicators. It returns True if either the tool name
        matches a known completion tool or the response text contains
        completion patterns.

        Args:
            tool_name: The name of the tool being invoked
            tool_arguments: The arguments passed to the tool (currently unused)
            response_text: Optional text content to check for completion patterns

        Returns:
            True if this represents a completion signal, False otherwise

        Examples:
            >>> CompletionSignalDetector.is_completion_signal("task_complete")
            True
            >>> CompletionSignalDetector.is_completion_signal(
            ...     "some_tool",
            ...     response_text="The task is complete"
            ... )
            True
            >>> CompletionSignalDetector.is_completion_signal(
            ...     "write_file",
            ...     response_text="Working on the implementation"
            ... )
            False
        """
        # Check if tool name indicates completion
        if tool_name and cls._is_completion_tool(tool_name):
            return True

        # Check if response text contains completion patterns
        if response_text and cls._contains_completion_pattern(response_text):
            return True

        return False

    @classmethod
    def _is_completion_tool(cls, tool_name: str) -> bool:
        """Check if tool name indicates completion.

        Performs case-insensitive matching with normalization to handle
        variations in tool naming conventions.

        Args:
            tool_name: The name of the tool to check

        Returns:
            True if the tool name indicates completion, False otherwise
        """
        if not tool_name:
            return False

        # Normalize the input tool name: lowercase, remove underscores
        normalized_input = tool_name.lower().replace("_", "")

        # Check against all completion tool patterns with the same normalization
        for pattern in cls.COMPLETION_TOOLS:
            normalized_pattern = pattern.replace("_", "")
            if normalized_input == normalized_pattern:
                return True

        return False

    @classmethod
    def _contains_completion_pattern(cls, text: str) -> bool:
        """Check if text contains completion patterns.

        Uses regex pattern matching to identify completion indicators
        in the provided text.

        Args:
            text: The text to check for completion patterns

        Returns:
            True if the text contains completion patterns, False otherwise
        """
        if not text:
            return False

        # Check if any completion pattern matches the text
        for pattern in cls.COMPLETION_PATTERNS:
            if pattern.search(text):
                return True

        return False
