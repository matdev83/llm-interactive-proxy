from __future__ import annotations

from src.core.interfaces.command_content_processor_interface import (
    ICommandContentProcessor,
)
from src.core.services.command_sanitizer import CommandSanitizer


class CommandContentProcessor(ICommandContentProcessor):
    """Minimal content processor: sanitizes command from a text part."""

    def __init__(self) -> None:
        self._sanitizer = CommandSanitizer()

    def process_part(self, text: str) -> str:
        return self._sanitizer.sanitize(text)
