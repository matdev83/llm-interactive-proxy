from __future__ import annotations

from typing import Protocol


class ICommandSanitizer(Protocol):
    """Removes command tokens from user-visible content consistently.

    Implementations should not execute commands; they only transform text.
    """

    def sanitize(self, content: str) -> str:
        """Return content with the first command occurrence removed.

        Args:
            content: Original message content

        Returns:
            Sanitized content with command removed and whitespace normalized
            in a predictable manner.
        """
        ...
