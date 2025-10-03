from __future__ import annotations

from typing import Protocol


class ICommandContentProcessor(Protocol):
    """Transforms structured content parts while respecting command stripping."""

    def process_part(self, text: str) -> str:
        """Return transformed text for a single content part."""
        ...
