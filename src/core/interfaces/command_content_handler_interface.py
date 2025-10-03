"""Interface for handling command content (string or list)."""

from abc import ABC, abstractmethod

from src.core.domain.chat import MessageContentPart


class ICommandContentHandler(ABC):
    """Interface for handling command content (string or list)."""

    @abstractmethod
    async def handle_string_content(self, content: str) -> tuple[str, bool, bool]:
        """Handles string content, processes commands, and returns modified content."""

    @abstractmethod
    async def handle_list_content(
        self, parts: list[MessageContentPart]
    ) -> tuple[list[MessageContentPart], bool, bool]:
        """Handles list content, processes commands, and returns modified content."""
