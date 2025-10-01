"""
Core data structures for the command system.
"""

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
