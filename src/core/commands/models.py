"""
Core data structures for the command system.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Command:
    """
    Represents a parsed command with its name and arguments.

    Attributes:
        name: The name of the command.
        args: A mapping of argument names to their values.
    """

    name: str
    args: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedCommand:
    """Represents a command parsed from raw text."""

    command: Command
    matched_text: str
    start: int
    end: int


class CommandResultWrapper:
    """Lightweight wrapper around command handler results.

    Historically the wrapper was defined inside ``process_commands`` which meant
    every invocation created a brand new class object.  Instances produced in
    separate calls therefore had different types which broke identity-based
    checks and made it impossible to import the wrapper for typing or
    isinstance() checks.  By hoisting the class to module scope we ensure the
    wrapper has a single, stable definition while keeping the behaviour
    identical to the previous implementation.
    """

    def __init__(self, command_name: str, result: Any) -> None:
        self.name = command_name
        self.message = result.message
        self.success = result.success
        self.new_state = getattr(result, "new_state", None)
        self._original_result = result

    @property
    def result(self) -> Any:
        """Expose the original command result for callers that need it."""

        return self._original_result
