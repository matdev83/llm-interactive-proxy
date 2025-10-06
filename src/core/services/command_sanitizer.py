from __future__ import annotations

from src.core.interfaces.command_sanitizer_interface import ICommandSanitizer
from src.core.services.command_utils import get_command_pattern


class CommandSanitizer(ICommandSanitizer):
    """Consistent command stripping aligned with existing tests/behavior.

    Rules:
    - Detect the first command using the shared get_command_pattern("!/")
    - If command is at the end, drop the suffix and keep prefix trimmed
    - If in the middle, join prefix and suffix with a single space
    - Preserve two spaces only for the legacy unknown-command branch (not here)
    """

    def sanitize(self, content: str) -> str:
        if not content:
            return content

        pattern = get_command_pattern("!/")
        m = pattern.search(content)
        if not m:
            return content

        before = content[: m.start()]
        after = content[m.end() :]

        if before and after:
            # Middle: one space between
            return f"{before.rstrip()} {after.lstrip()}"
        if before:
            # Command at end
            return before.rstrip()
        # Command at start
        return after.lstrip()
