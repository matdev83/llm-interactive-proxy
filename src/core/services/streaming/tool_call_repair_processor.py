"""
Tool call repair processor - now a transparent pass-through.

DESIGN DECISION: Virtual tool call detection (parsing XML from message content)
has been DISABLED because:
1. Clients like Cline, RooCode, KiloCode parse XML tool calls themselves
2. Attempting to detect XML causes false positives (brain_dump, memory_bank, etc.)
3. It interferes with client-specific structured prompting
4. Native tool_calls (already structured) are passed through unchanged

The proxy should be TRANSPARENT - content passes through as-is.
Tool call detection is the CLIENT's responsibility, not the proxy's.
"""

from __future__ import annotations

import logging

from src.core.domain.streaming_response_processor import (
    IStreamProcessor,
    StreamingContent,
)
from src.core.interfaces.tool_call_repair_service_interface import (
    IToolCallRepairService,
)
from src.core.services.streaming.stream_context_registry import (
    StreamingContextRegistry,
)

logger = logging.getLogger(__name__)


class ToolCallRepairProcessor(IStreamProcessor):
    """
    Stream processor that passes content through transparently.

    This processor no longer attempts to detect XML tool calls from message
    content. Clients like Cline, RooCode, and KiloCode parse XML tool calls
    themselves - the proxy should not interfere with this.

    Native tool_calls (already structured in the response) are passed through
    unchanged.
    """

    def __init__(
        self,
        tool_call_repair_service: IToolCallRepairService,
        *,
        max_buffer_bytes: int | None = None,
        registry: StreamingContextRegistry | None = None,
    ) -> None:
        # Keep constructor signature for compatibility, but don't use these
        self.tool_call_repair_service = tool_call_repair_service
        self._max_buffer_bytes = max_buffer_bytes or 64 * 1024
        self._registry = registry or StreamingContextRegistry()

    async def process(self, content: StreamingContent) -> StreamingContent:
        """
        Pass through content transparently - no XML detection or modification.
        """
        return content

    def reset(self) -> None:
        """Reset buffer state (no-op, kept for interface compatibility)."""
        self._registry.reset()


# Keep type alias for backward compatibility
ServiceToolCallRepairProcessor = ToolCallRepairProcessor
