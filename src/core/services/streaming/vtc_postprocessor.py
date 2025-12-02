"""
VTC Post-Processor - Converts internal tool calls back to XML format.

This processor handles the final step of VTC processing:
1. Takes tool calls from metadata (potentially modified by core pipeline)
2. Serializes them back to XML format for Cline-like clients
3. Appends XML to content and clears tool_calls to prevent duplicate delivery

This processor is only active for sessions with vtc_enabled=True.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.core.ports.streaming_contracts import IStreamProcessor, StreamingContent
from src.core.services.streaming.stream_context_registry import StreamingContextRegistry
from src.core.services.vtc_xml_parser import serialize_tool_calls_to_xml

logger = logging.getLogger(__name__)


@dataclass
class VTCPostProcessorConfig:
    """Configuration for VTC post-processor."""

    # Whether to append newlines before XML
    prepend_newlines: bool = True

    # Number of newlines to prepend
    newline_count: int = 2


class VTCPostProcessor(IStreamProcessor):
    """
    Stream processor that converts internal tool calls back to XML format.

    For sessions with vtc_enabled=True in metadata, this processor:
    1. Checks for tool_calls in metadata
    2. Serializes them to XML using serialize_tool_calls_to_xml()
    3. Appends the XML to content
    4. Removes tool_calls from metadata to prevent duplicate delivery

    This ensures Cline-like clients receive tool calls in their expected
    XML format, regardless of how they were processed internally.
    """

    def __init__(
        self,
        registry: StreamingContextRegistry,
        config: VTCPostProcessorConfig | None = None,
    ) -> None:
        """
        Initialize the VTC post-processor.

        Args:
            registry: The streaming context registry (for consistency with pre-processor).
            config: Optional configuration settings.
        """
        self._registry = registry
        self._config = config or VTCPostProcessorConfig()

    async def process(self, content: StreamingContent) -> StreamingContent:
        """
        Process streaming content, converting tool calls to XML for VTC sessions.

        Args:
            content: The streaming content chunk to process.

        Returns:
            Processed streaming content with XML tool calls in content.
        """
        # Check if VTC is enabled for this stream
        vtc_enabled = content.metadata.get("vtc_enabled", False)
        if not vtc_enabled:
            return content

        # Check for tool_calls in metadata
        tool_calls = content.metadata.get("tool_calls")
        if not tool_calls:
            return content

        # Validate tool_calls is a list
        if not isinstance(tool_calls, list):
            logger.warning(
                "VTC post-processor received non-list tool_calls: %s",
                type(tool_calls).__name__,
            )
            return content

        # Serialize tool calls to XML
        xml_content = serialize_tool_calls_to_xml(tool_calls)
        if not xml_content:
            return content

        logger.debug(
            "VTC post-processor serializing %d tool calls to XML", len(tool_calls)
        )

        # Get current content as string
        current_content = self._get_content_text(content)

        # Build new content with XML appended
        if current_content:
            if self._config.prepend_newlines:
                separator = "\n" * self._config.newline_count
                new_content = f"{current_content}{separator}{xml_content}"
            else:
                new_content = f"{current_content}{xml_content}"
        else:
            new_content = xml_content

        # Create new metadata without tool_calls (to prevent duplicate delivery)
        new_metadata = {k: v for k, v in content.metadata.items() if k != "tool_calls"}

        return StreamingContent(
            content=new_content,
            metadata=new_metadata,
            is_done=content.is_done,
            is_empty=not new_content,
            stream_id=content.stream_id,
            is_cancellation=content.is_cancellation,
            usage=content.usage,
            raw_data=content.raw_data,
        )

    def _get_content_text(self, content: StreamingContent) -> str:
        """
        Extract text content from StreamingContent.

        Args:
            content: The streaming content.

        Returns:
            String content.
        """
        if isinstance(content.content, str):
            return content.content
        if isinstance(content.content, bytes):
            return content.content.decode("utf-8", errors="replace")
        if isinstance(content.content, dict):
            # Handle dict content - extract text if present
            text_value = content.content.get("content", "")
            return str(text_value) if text_value else ""
        return ""

    def reset(self) -> None:
        """Reset processor state for new stream."""
        # Stateless processor, nothing to reset
