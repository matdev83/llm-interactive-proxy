from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from src.core.commands.parser import ParsedCommand


@dataclass(frozen=True)
class FilteredCommand:
    """Command that passed tail filtering with message metadata."""

    command: ParsedCommand
    message_index: int


class CommandMatchFilter:
    """Filter that keeps only commands allowed for execution."""

    def filter_tail_commands(
        self,
        parsed_commands: Sequence[ParsedCommand],
        tail_text: str,
        message_index: int,
    ) -> list[FilteredCommand]:
        """Return commands that appear at the end of the provided tail text."""
        if not parsed_commands:
            return []

        trimmed_tail = tail_text.rstrip()
        if not trimmed_tail:
            return []

        filtered: list[FilteredCommand] = []
        for parsed in parsed_commands:
            if parsed.end != len(trimmed_tail):
                continue

            matched = parsed.matched_text
            if not matched:
                continue

            if not trimmed_tail.endswith(matched):
                continue

            filtered.append(
                FilteredCommand(command=parsed, message_index=message_index)
            )

        return filtered
