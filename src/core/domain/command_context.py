"""
Command Context Domain Model

This module defines the command context protocol for the new SOLID architecture.
"""

from __future__ import annotations

from typing import Protocol


class CommandContext(Protocol):
    """Protocol for command execution context to decouple commands from FastAPI app."""

    @property
    def backend_type(self) -> str | None:
        """Get the current backend type."""
        ...

    @backend_type.setter
    def backend_type(self, value: str) -> None:
        """Set the backend type."""
        ...

    @property
    def api_key_redaction_enabled(self) -> bool:
        """Get API key redaction setting."""
        ...

    @api_key_redaction_enabled.setter
    def api_key_redaction_enabled(self, value: bool) -> None:
        """Set API key redaction setting."""
        ...

    @property
    def command_prefix(self) -> str:
        """Get command prefix."""
        ...

    @command_prefix.setter
    def command_prefix(self, value: str) -> None:
        """Set command prefix."""
        ...

    @property
    def interactive_mode(self) -> bool:
        """Get interactive mode setting."""
        ...

    @interactive_mode.setter
    def interactive_mode(self, value: bool) -> None:
        """Set interactive mode setting."""
        ...

    @property
    def reasoning_effort(self) -> str | None:
        """Get reasoning effort setting."""
        ...

    @reasoning_effort.setter
    def reasoning_effort(self, value: str | None) -> None:
        """Set reasoning effort setting."""
        ...

    @property
    def thinking_budget(self) -> float | None:
        """Get thinking budget setting."""
        ...

    @thinking_budget.setter
    def thinking_budget(self, value: float | None) -> None:
        """Set thinking budget setting."""
        ...

    @property
    def temperature(self) -> float | None:
        """Get temperature setting."""
        ...

    @temperature.setter
    def temperature(self, value: float | None) -> None:
        """Set temperature setting."""
        ...

    @property
    def loop_detection_enabled(self) -> bool | None:
        """Get loop detection enabled setting."""
        ...

    @loop_detection_enabled.setter
    def loop_detection_enabled(self, value: bool | None) -> None:
        """Set loop detection enabled setting."""
        ...

    @property
    def tool_loop_detection_enabled(self) -> bool | None:
        """Get tool loop detection enabled setting."""
        ...

    @tool_loop_detection_enabled.setter
    def tool_loop_detection_enabled(self, value: bool | None) -> None:
        """Set tool loop detection enabled setting."""
        ...

    @property
    def tool_loop_max_repeats(self) -> int | None:
        """Get tool loop max repeats setting."""
        ...

    @tool_loop_max_repeats.setter
    def tool_loop_max_repeats(self, value: int | None) -> None:
        """Set tool loop max repeats setting."""
        ...

    @property
    def tool_loop_ttl_seconds(self) -> int | None:
        """Get tool loop TTL seconds setting."""
        ...

    @tool_loop_ttl_seconds.setter
    def tool_loop_ttl_seconds(self, value: int | None) -> None:
        """Set tool loop TTL seconds setting."""
        ...

    @property
    def tool_loop_mode(self) -> str | None:
        """Get tool loop mode setting."""
        ...

    @tool_loop_mode.setter
    def tool_loop_mode(self, value: str | None) -> None:
        """Set tool loop mode setting."""
        ...
