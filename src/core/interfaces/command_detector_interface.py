from __future__ import annotations

from typing import Protocol


class ICommandDetector(Protocol):
    """Detects commands within message content and returns parsed details."""

    def detect(self, content: str) -> dict[str, object] | None:
        """Return parsed command info or None if no command is present.

        Expected keys when present: cmd_name (str), args_str (str|None),
        match_start (int), match_end (int).
        """
        ...
