"""Shared helpers for response metadata exposed to clients."""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic.types import JsonValue

logger = logging.getLogger(__name__)

_INTERNAL_METADATA_KEYS: frozenset[str] = frozenset({"_synthetic_blocking_envelope"})


def filter_json_serializable_client_metadata(
    metadata: dict[str, Any],
) -> dict[str, JsonValue]:
    """Keep only JSON-serializable metadata entries.

    Drops ``original_request`` and other keys whose values are not JSON-serializable.
    """
    json_serializable_metadata: dict[str, JsonValue] = {}
    for key, value in metadata.items():
        if key == "original_request" or key in _INTERNAL_METADATA_KEYS:
            continue
        try:
            json.dumps(value)
            json_serializable_metadata[key] = value  # type: ignore[assignment]
        except (TypeError, ValueError):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Skipping non-JSON-serializable metadata key: %s", key)
    return json_serializable_metadata
