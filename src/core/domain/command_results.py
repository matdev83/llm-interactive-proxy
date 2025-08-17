"""
Command Results Domain Model

This module defines the domain model for command results in the new SOLID architecture.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CommandResult:
    """
    Result of a command execution.

    This class represents the result of executing a command in the new architecture.
    It is compatible with the legacy CommandResult class but adds additional
    functionality for the new architecture.
    """

    success: bool
    message: str
    name: str = ""
    data: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        """Initialize default values."""
        if self.data is None:
            self.data = {}
        # If name is not provided but data contains a name, use that
        if not self.name and self.data and "name" in self.data:
            self.name = self.data["name"]
