"""Interface for command parsing."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from src.core.commands.parser import ParsedCommand


class ICommandParser(Protocol):
    """Interface for parsing commands from raw message text."""

    def parse(
        self, content: str, *, command_prefix: str | None = None
    ) -> Sequence[ParsedCommand]:
        """Return all commands found in *content*."""
        ...
