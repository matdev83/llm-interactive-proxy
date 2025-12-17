"""
Parser strategy interface for raw chunk parsing.

This module defines the interface for parser strategies that convert raw backend
chunks into StreamingContent instances.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.core.domain.streaming.streaming_content import StreamingContent


class IParserStrategy(ABC):
    """Interface for parser strategies that convert raw data to StreamingContent.

    Each strategy handles a specific input format (e.g., OpenAI dict, SSE bytes,
    ProcessedResponse). The RawChunkParser uses a chain of strategies to find
    the appropriate parser for a given input.
    """

    @abstractmethod
    def can_parse(self, raw_data: Any) -> bool:
        """Check if this strategy can parse the given raw data.

        Args:
            raw_data: The raw data to check

        Returns:
            True if this strategy can parse the data, False otherwise
        """
        pass

    @abstractmethod
    def parse(self, raw_data: Any) -> StreamingContent:
        """Parse raw data into StreamingContent.

        Args:
            raw_data: Raw data from backend

        Returns:
            A new StreamingContent instance

        Raises:
            ValueError: If parsing fails (should not happen if can_parse returns True)
        """
        pass


__all__ = ["IParserStrategy"]

