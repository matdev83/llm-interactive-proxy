"""
Testing helpers for streaming responses.

This module provides helper functions for creating consistent
streaming responses for testing purposes.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any, List, Union


async def create_streaming_generator(
    content: List[str], 
    model: str = "mock-model", 
    chunk_delay_seconds: float = 0.01
) -> AsyncGenerator[bytes, None]:
    """
    Create a streaming generator for testing that produces chunks in SSE format.

    Args:
        content: List of content chunks to stream
        model: Model name to include in response
        chunk_delay_seconds: Delay between chunks (default: 0.01s)

    Returns:
        An async generator that yields SSE chunks as bytes
    """
    for i, chunk in enumerate(content):
        # Create a standard SSE chunk
        data = {
            "id": f"mock-chunk-{i}",
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": model,
            "choices": [
                {"index": 0, "delta": {"content": chunk}}
            ],
        }
        # Format as SSE
        yield f"data: {json.dumps(data)}\n\n".encode()
        await asyncio.sleep(chunk_delay_seconds)

    # Final chunk
    yield b"data: [DONE]\n\n"
