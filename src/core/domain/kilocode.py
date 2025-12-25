"""KiloCode domain models."""

from __future__ import annotations

from typing import Any

from src.core.domain.base import ValueObject


class KiloCodeToolResult(ValueObject):
    """Result of a KiloCode tool execution."""
    output: str
    exit_code: int
    error: str | None = None
    
    # Tool-specific fields
    file_path: str | None = None
    size: int | None = None
    directory: str | None = None
    count: int | None = None
    pattern: str | None = None
    matches_count: int | None = None
    tool_name: str | None = None
    note: str | None = None
    completion_result: str | None = None
    marker_type: str | None = None
    followup_question: str | None = None
    
    def __getitem__(self, key: str) -> Any:
        """Allow dictionary-like access for backward compatibility."""
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        """Allow dictionary-like access for backward compatibility."""
        return getattr(self, key, default)
