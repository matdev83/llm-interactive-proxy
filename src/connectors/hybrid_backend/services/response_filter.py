"""ResponseFilter service for filtering reasoning tags from responses.

This service extracts filtering logic from HybridConnector to provide
focused, testable components for removing reasoning tags from various content types.

Requirements satisfied:
- Req 2.5: ResponseFilter extraction
- Req 3: Protocol-first design
"""

import json
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.domain.responses import StreamingResponseEnvelope
    from src.core.interfaces.response_processor_interface import ProcessedResponse

from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse


class ResponseFilter:
    """Service for filtering reasoning tags from response content.

    Handles filtering of reasoning tags from strings, dicts, lists, bytes,
    and streaming responses.
    """

    # Compiled regex patterns for reasoning tag removal
    _REASONING_PATTERNS = [
        re.compile(r"<thinking>.*?</thinking>", re.DOTALL | re.IGNORECASE),
        re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE),
        re.compile(r"<reasoning>.*?</reasoning>", re.DOTALL | re.IGNORECASE),
        re.compile(r"<reason>.*?</reason>", re.DOTALL | re.IGNORECASE),
    ]

    _INSTRUCTION_PATTERN = re.compile(
        r"Consider this reasoning when formulating your response:\s*",
        re.IGNORECASE,
    )

    def _strip_reasoning_tags(self, content: str) -> str:
        """Strip reasoning tags from content.

        Args:
            content: Content that may contain reasoning tags

        Returns:
            Content with reasoning tags and their content removed
        """
        cleaned_content = content
        for pattern in self._REASONING_PATTERNS:
            cleaned_content = pattern.sub("", cleaned_content)

        # Also remove the instruction prefix if present
        cleaned_content = self._INSTRUCTION_PATTERN.sub("", cleaned_content)

        return cleaned_content

    def _filter_json_content(self, data: Any) -> Any:
        """Recursively remove reasoning content from JSON-like structures."""
        if isinstance(data, dict):
            filtered: dict[str, Any] = {}
            for key, value in data.items():
                if key == "reasoning_content":
                    continue
                filtered[key] = self._filter_json_content(value)
            return filtered

        if isinstance(data, list):
            return [self._filter_json_content(item) for item in data]

        if isinstance(data, str):
            return self._strip_reasoning_tags(data)

        return data

    def filter_content(self, content: Any) -> Any:
        """Filter reasoning tags from response content.

        This method handles various content types and ensures reasoning
        tags are removed from all parts of the response, including tool calls.

        Args:
            content: Response content (can be string, dict, bytes, or list)

        Returns:
            Filtered content with reasoning tags removed
        """
        # Handle bytes content (SSE chunks)
        if isinstance(content, bytes):
            try:
                content_str = content.decode("utf-8")
            except UnicodeDecodeError:
                # If we can't decode, return as-is
                return content
        elif isinstance(content, str):
            content_str = content
        elif isinstance(content, dict):
            return self._filter_json_content(content)
        elif isinstance(content, list):
            return [self.filter_content(item) for item in content]
        else:
            # For other types, return as-is
            return content

        # Check if this is an SSE data line
        if content_str.startswith("data: "):
            data_part = content_str[6:].strip()

            # Skip [DONE] markers
            if data_part == "[DONE]":
                return content

            try:
                # Parse the JSON data
                data = json.loads(data_part)

                # Filter the JSON payload recursively
                cleaned = self._filter_json_content(data)

                # Reconstruct the SSE line
                filtered_data = json.dumps(cleaned, ensure_ascii=False)
                return (
                    f"data: {filtered_data}\n\n".encode()
                    if isinstance(content, bytes)
                    else f"data: {filtered_data}\n\n"
                )

            except json.JSONDecodeError:
                # If we can't parse JSON, just strip tags from the string
                filtered_str = self._strip_reasoning_tags(content_str)
                return (
                    filtered_str.encode("utf-8")
                    if isinstance(content, bytes)
                    else filtered_str
                )

        # For non-SSE content, just strip tags
        filtered_str = self._strip_reasoning_tags(content_str)
        return (
            filtered_str.encode("utf-8") if isinstance(content, bytes) else filtered_str
        )

    async def filter_stream(
        self, response: StreamingResponseEnvelope
    ) -> StreamingResponseEnvelope:
        """Filter reasoning tags from streaming response.

        Args:
            response: Original streaming response from execution model

        Returns:
            Filtered streaming response with reasoning tags removed
        """

        async def filtered_stream():
            """Generator that filters each chunk of the response stream."""
            if response.content is None:
                return

            async for chunk in response.content:
                # Filter the content
                filtered_content = self.filter_content(chunk.content)

                # Strip reasoning artifacts from metadata as well
                cleaned_metadata = dict(chunk.metadata or {})
                for key in ("reasoning", "reasoning_content", "reasoning_format"):
                    cleaned_metadata.pop(key, None)

                # Create new ProcessedResponse with filtered content
                filtered_chunk = ProcessedResponse(
                    content=filtered_content,
                    usage=chunk.usage,
                    metadata=cleaned_metadata,
                )

                yield filtered_chunk

        # Return new StreamingResponseEnvelope with filtered stream
        return StreamingResponseEnvelope(
            content=filtered_stream(),
            media_type=response.media_type,
            headers=response.headers,
            cancel_callback=response.cancel_callback,
        )
