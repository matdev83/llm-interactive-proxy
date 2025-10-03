from __future__ import annotations

from typing import Protocol


class ICommandArgumentParser(Protocol):
    """Parses a command argument string into a structured dictionary.

    Implementations should be pure and side-effect free.
    """

    def parse(self, args_str: str | None) -> dict[str, object]:
        """Parse an argument string into a dict of argument name to value.

        Args:
            args_str: Raw argument string (may be None or empty)

        Returns:
            A dictionary of parsed arguments. Returns an empty dict when no
            arguments are present or parsing yields no results.
        """
        ...
