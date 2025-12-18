"""
Sentinel management for streaming.

This module contains SentinelManager for done marker handling.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.ports.streaming_contracts import StreamingContent

__all__ = ["SentinelManager"]


class SentinelManager:
    """Centralized management of stream completion markers.

    This utility ensures consistent handling of [DONE] markers across
    all backends and components.
    """

    DONE_MARKER = "[DONE]"

    @staticmethod
    def create_done_chunk() -> StreamingContent:
        """Create standardized [DONE] chunk.

        Returns:
            A StreamingContent chunk representing stream completion
        """
        from src.core.ports.streaming_contracts import StreamingContent

        return StreamingContent(
            content=SentinelManager.DONE_MARKER,
            metadata={"finish_reason": "stop"},
            is_done=True,
        )

    @staticmethod
    def is_done_marker(chunk: StreamingContent) -> bool:
        """Check if chunk is a [DONE] marker.

        Args:
            chunk: The chunk to check

        Returns:
            True if this is a done marker, False otherwise
        """
        return chunk.is_done or chunk.content == SentinelManager.DONE_MARKER

    @staticmethod
    def format_sse_done() -> bytes:
        """Format [DONE] as SSE.

        Returns:
            SSE-formatted done marker
        """
        return b"data: [DONE]\n\n"



