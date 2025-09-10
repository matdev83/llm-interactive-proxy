from abc import ABC, abstractmethod
from typing import Any

from src.core.domain.chat import ChatResponse


class IResponseParser(ABC):
    """
    Interface for parsing various response formats into a standardized structure.
    """

    @abstractmethod
    def parse_response(
        self,
        raw_response: ChatResponse | dict[str, Any] | str,
        is_streaming: bool = False,
    ) -> dict[str, Any]:
        """
        Parses a raw response into a standardized dictionary format.

        Args:
            raw_response: The raw response, which can be a ChatResponse object,
                          a dictionary, or a string.
            is_streaming: A boolean indicating if the response is part of a streaming sequence.

        Returns:
            A dictionary containing the parsed response data, including content,
            usage, and other metadata.
        """

    @abstractmethod
    def extract_content(self, parsed_response: dict[str, Any]) -> str:
        """
        Extracts the main content string from a parsed response dictionary.

        Args:
            parsed_response: The dictionary containing the parsed response data.

        Returns:
            The extracted content string.
        """

    @abstractmethod
    def extract_usage(self, parsed_response: dict[str, Any]) -> dict[str, Any] | None:
        """
        Extracts usage information from a parsed response dictionary.

        Args:
            parsed_response: The dictionary containing the parsed response data.

        Returns:
            A dictionary containing usage details, or None if not available.
        """

    @abstractmethod
    def extract_metadata(
        self, parsed_response: dict[str, Any]
    ) -> dict[str, Any] | None:
        """
        Extracts metadata from a parsed response dictionary.

        Args:
            parsed_response: The dictionary containing the parsed response data.

        Returns:
            A dictionary containing metadata, or None if not available.
        """
