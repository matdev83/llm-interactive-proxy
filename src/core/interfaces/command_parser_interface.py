"""Interface for command parsing."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.core.domain.chat import ChatMessage


class ICommandParser(ABC):
    """Interface for parsing commands from chat messages."""

    @abstractmethod
    async def parse(self, messages: list[ChatMessage]) -> list[dict[str, Any]]:
        """Extract commands with arguments and positions from messages.

        Args:
            messages: List of chat messages to parse

        Returns:
            List of parsed commands with their details
        """
