"""
Core data structures for the command system.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.interfaces.domain_entities_interface import ISessionState


@dataclass(frozen=True)
class CommandResult:
    """
    Represents the result of a command execution.

    Attributes:
        success: Whether the command executed successfully.
        message: A message to be displayed to the user.
        new_state: The updated session state, if any.
    """

    success: bool
    message: str
    new_state: "ISessionState | None" = None


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
