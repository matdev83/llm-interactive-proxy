"""Shared helpers for BackendStreamingResponseHandler unit tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

from src.core.interfaces.response_processor_interface import ProcessedResponse


async def async_chunk_iterator(
    chunks: list[ProcessedResponse],
) -> AsyncIterator[ProcessedResponse]:
    """Helper to create async iterator from list."""
    for chunk in chunks:
        yield chunk
