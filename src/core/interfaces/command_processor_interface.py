"""
Interface for command processing.

This module defines the interface for processing commands in messages.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext


class ICommandProcessor(ABC):
    """Interface for processing commands in messages."""

    @abstractmethod
    async def process_messages(
        self,
        messages: list[Any],
        session_id: str,
        context: RequestContext | None = None,
    ) -> ProcessedResult:
        """Process commands in a list of chat messages.

        Args:
            messages: The messages to process.

        Returns:
            A tuple containing:
            - The list of messages after processing, with commands removed or modified.
            - A boolean indicating if any commands were processed.
        """
