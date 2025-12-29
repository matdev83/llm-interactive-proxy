"""Tool execution domain models."""

from __future__ import annotations

from typing import Any

from pydantic.types import JsonValue

from src.core.domain.base import ValueObject


class UniversalToolResult(ValueObject):
    """Result of a universal tool execution."""

    output: str
    exit_code: int
    error: str | None = None

    # Additional metadata
    metadata: dict[str, JsonValue] = {}

    def __getitem__(self, key: str) -> Any:
        """Allow dictionary-like access for backward compatibility."""
        if key == "output":
            return self.output
        if key == "exit_code":
            return self.exit_code
        if key == "error":
            return self.error
        return self.metadata.get(key)

    def get(self, key: str, default: Any = None) -> Any:
        """Allow dictionary-like access for backward compatibility."""
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key: str) -> bool:
        """Allow 'in' operator for backward compatibility."""
        if key in ("output", "exit_code", "error"):
            return True
        return key in self.metadata

    def __iter__(self):  # type: ignore[override]
        """Allow iterating over keys for backward compatibility."""
        yield ("output", self.output)
        yield ("exit_code", self.exit_code)
        yield ("error", self.error)
        yield from self.metadata.items()

    def update(self, other: dict[str, Any]) -> None:
        """Allow update-like behavior for backward compatibility."""
        # This is a bit of a hack since ValueObject is frozen,
        # but in practice some code might try to update the dict.
        # Since it's frozen, we can't actually update it if it's an instance.
        # If code uses .update(), it will fail if it's a frozen Pydantic model.
        # But we'll see if any code actually does that.
