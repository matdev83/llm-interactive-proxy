"""SSE formatter implementation.

This module contains the SSEFormatter class for formatting content as
Server-Sent Events (SSE) bytes.
"""

from __future__ import annotations

import json


class SSEFormatter:
    """Format content as SSE bytes."""

    def format_chunk(self, content: dict | bytes | str) -> bytes:
        """Format a single chunk as SSE bytes.

        Args:
            content: Content to format (dict, bytes, or str)

        Returns:
            SSE-formatted bytes:
            - Dict → data: {json}\n\n
            - Bytes → passed through
            - String → encoded to bytes
        """
        if isinstance(content, dict):
            # Use dict(content) to safely convert StopChunkWithUsage to plain dict.
            # StopChunkWithUsage is a dict subclass that raises an error on str(),
            # but json.dumps() doesn't call __str__(), so we need to explicitly
            # convert to plain dict to avoid accidental stringification elsewhere.
            # Format as SSE: data: {json}\n\n
            # Note: Using default separators to include spaces for readability
            sse_line = f"data: {json.dumps(dict(content), ensure_ascii=False)}\n\n"
            return sse_line.encode("utf-8")
        elif isinstance(content, bytes):
            return content
        else:
            return str(content).encode("utf-8")

