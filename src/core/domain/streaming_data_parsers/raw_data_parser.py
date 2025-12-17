from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from src.core.domain.streaming_content import StreamingContent

logger = logging.getLogger(__name__)


class IRawDataParser(ABC):
    """Interface for parsing raw streaming data into StreamingContent."""

    @abstractmethod
    def parse(self, data: Any) -> StreamingContent:
        """Parse raw data into a StreamingContent object."""


class BytesParser(IRawDataParser):
    """Parses bytes data into StreamingContent.

    This parser delegates to StreamingContent.from_raw() to use the
    centralized parsing logic.
    """

    def parse(self, data: bytes) -> StreamingContent:
        """Parse bytes data into StreamingContent.

        Delegates to StreamingContent.from_raw() which uses the strategy-based
        parser chain.

        Args:
            data: Bytes data to parse

        Returns:
            StreamingContent instance
        """
        return StreamingContent.from_raw(data)


class DictParser(IRawDataParser):
    """Parses dictionary data (OpenAI-compatible) into StreamingContent.

    This parser delegates to StreamingContent.from_raw() to use the
    centralized parsing logic.
    """

    def parse(self, data: dict[str, Any]) -> StreamingContent:
        """Parse dictionary data into StreamingContent.

        Delegates to StreamingContent.from_raw() which uses the strategy-based
        parser chain to handle OpenAI, Anthropic, Gemini, and other formats.

        Args:
            data: Dictionary data to parse

        Returns:
            StreamingContent instance
        """
        return StreamingContent.from_raw(data)


class StringParser(IRawDataParser):
    """Parses string data into StreamingContent.

    This parser delegates to StreamingContent.from_raw() to use the
    centralized parsing logic.
    """

    def parse(self, data: str) -> StreamingContent:
        """Parse string data into StreamingContent.

        Delegates to StreamingContent.from_raw() which uses the strategy-based
        parser chain to handle JSON strings, SSE strings, and plain strings.

        Args:
            data: String data to parse

        Returns:
            StreamingContent instance
        """
        return StreamingContent.from_raw(data)


class StreamingContentParser(IRawDataParser):
    """Handles already processed StreamingContent objects."""

    def parse(self, data: StreamingContent) -> StreamingContent:
        return data
