"""Chunk normalizer for converting connector outputs to ProcessedChunkContent.

This module provides utilities for normalizing provider-specific objects and
connector outputs into boundary-safe ProcessedChunkContent types before they
cross boundaries into ProcessedResponse.
"""

from __future__ import annotations

from typing import Any

from src.core.domain.translation_utils.json_utils import (
    is_json_serializable,
    sanitize_dict_for_json,
)
from src.core.interfaces.response_processor_interface import ProcessedChunkContent


def normalize_to_processed_chunk_content(content: Any) -> ProcessedChunkContent:
    """Normalize connector output to ProcessedChunkContent.

    Converts provider-specific objects, complex types, and ad-hoc dicts into
    boundary-safe ProcessedChunkContent (bytes | str | dict[str, JsonValue] | None).

    This function ensures that:
    - Provider-specific objects are normalized before crossing boundaries
    - Dict values are JSON-serializable (JsonValue)
    - Shallow transformations are used (no deep copying of large payloads)
    - Copy-on-write semantics are preserved

    Args:
        content: Raw content from connector (Any type)

    Returns:
        Normalized ProcessedChunkContent (bytes | str | dict[str, JsonValue] | None)

    Examples:
        >>> normalize_to_processed_chunk_content("text")
        'text'
        >>> normalize_to_processed_chunk_content(b"bytes")
        b'bytes'
        >>> normalize_to_processed_chunk_content({"key": "value"})
        {'key': 'value'}
        >>> normalize_to_processed_chunk_content(None)
        None
    """
    # Handle None
    if content is None:
        return None

    # Handle str (already ProcessedChunkContent)
    if isinstance(content, str):
        return content

    # Handle bytes (already ProcessedChunkContent)
    if isinstance(content, bytes):
        return content

    # Handle bytearray (convert to bytes)
    if isinstance(content, bytearray):
        return bytes(content)

    # Handle dict - normalize to dict[str, JsonValue]
    if isinstance(content, dict):
        # Check if dict is already JSON-serializable
        if is_json_serializable(content):
            # Shallow copy to preserve copy-on-write semantics
            # The dict itself is copied, but nested structures are not deep-copied
            return dict(content)
        else:
            # Sanitize dict to remove non-JSON-serializable values
            # This preserves shallow copy semantics (nested dicts are not deep-copied)
            sanitized = sanitize_dict_for_json(content)
            return sanitized

    # Handle list/tuple - convert to string representation
    # Lists/tuples are not part of ProcessedChunkContent, so we stringify them
    if isinstance(content, (list, tuple)):
        return str(content)

    # Handle all other types - convert to string
    # This includes complex objects, provider-specific types, etc.
    return str(content)
