"""Canonical contract serialization utilities.

Provides deterministic serialization and secret-safe logging for canonical contracts.
Ensures stable capture/replay workflows and prevents sensitive data leakage.
"""

from __future__ import annotations

import contextlib
import json
from typing import Any

from src.core.common.logging_utils import redact_dict


def serialize_for_capture(contract: Any) -> bytes:
    """Serialize canonical contract for capture with deterministic ordering.

    Uses deterministic JSON serialization with sorted keys to ensure
    same input produces identical output for diff-based debugging and stable replay.

    Args:
        contract: Canonical contract (Pydantic model, dict, list, str, bytes)

    Returns:
        Deterministically serialized bytes

    Examples:
        >>> request = CanonicalChatRequest(model="gpt-4", messages=[...])
        >>> bytes_data = serialize_for_capture(request)
        >>> # Same request always produces identical bytes
    """
    # Handle bytes directly (already deterministic)
    if isinstance(contract, bytes):
        return contract

    # Handle bytearray
    if isinstance(contract, bytearray):
        return bytes(contract)

    # Handle strings (encode to bytes)
    if isinstance(contract, str):
        return contract.encode("utf-8")

    # Handle Pydantic models
    if hasattr(contract, "model_dump") and callable(contract.model_dump):
        try:
            # Use mode="json" to ensure JSON-safe types
            data = contract.model_dump(mode="json")
            return json.dumps(
                data, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        except (TypeError, ValueError, AttributeError):
            # Fallback to regular model_dump if mode="json" not supported
            try:
                data = contract.model_dump()
                return json.dumps(
                    data, sort_keys=True, ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
            except (TypeError, ValueError, AttributeError):
                # Final fallback: string representation
                return str(contract).encode("utf-8")

    # Handle dicts and lists
    if isinstance(contract, dict | list):
        return json.dumps(
            contract, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")

    # Handle objects with __dict__
    if hasattr(contract, "__dict__"):
        with contextlib.suppress(TypeError, ValueError):
            # Fall back to string representation if __dict__ conversion fails
            data = dict(contract.__dict__)
            return json.dumps(
                data, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")

    # Final fallback: string representation
    return str(contract).encode("utf-8")


def serialize_for_logging(contract: Any, *, redact: bool = True) -> str:
    """Serialize canonical contract for logging with optional secret redaction.

    Applies redaction to sensitive fields before serialization if redact=True.
    Uses deterministic JSON serialization with sorted keys for consistent log output.

    Args:
        contract: Canonical contract (Pydantic model, dict, list, etc.)
        redact: Whether to apply redaction (default: True)

    Returns:
        JSON string suitable for log messages

    Examples:
        >>> request = {"api_key": "sk-test", "model": "gpt-4"}
        >>> log_str = serialize_for_logging(request, redact=True)
        >>> # Contains redacted api_key: "***"
    """
    # Convert to dict representation for redaction
    if hasattr(contract, "model_dump") and callable(contract.model_dump):
        try:
            # Use mode="json" to ensure JSON-safe types
            data = contract.model_dump(mode="json")
        except (TypeError, ValueError, AttributeError):
            # Fallback to regular model_dump
            try:
                data = contract.model_dump()
            except (TypeError, ValueError, AttributeError):
                # Fallback: convert to dict if possible
                if hasattr(contract, "__dict__"):
                    data = dict(contract.__dict__)
                else:
                    data = {"_repr": str(contract)}
    elif isinstance(contract, dict):
        data = contract
    elif isinstance(contract, list):
        # Lists are serialized as-is (order preserved)
        # But we need to redact dict items within the list
        data = contract
    elif hasattr(contract, "__dict__"):
        data = dict(contract.__dict__)
    else:
        # Primitive types or unknown
        data = {"_value": contract}

    # Apply redaction if requested
    if redact:
        if isinstance(data, dict):
            data = redact_dict(data)
        elif isinstance(data, list):
            # Recursively redact dict items in lists (handles nested lists too)
            def _redact_list_item(item: Any) -> Any:
                """Recursively redact dicts in nested lists."""
                if isinstance(item, dict):
                    return redact_dict(item, mask="***")
                elif isinstance(item, list):
                    return [_redact_list_item(subitem) for subitem in item]
                else:
                    return item

            data = [_redact_list_item(item) for item in data]

    # Serialize with deterministic ordering
    return json.dumps(data, sort_keys=True, ensure_ascii=False, indent=None)


def serialize_dict_for_capture(data: dict[str, Any]) -> bytes:
    """Serialize dictionary for capture with deterministic key ordering.

    Helper function specifically for dict serialization in wire capture services.
    Ensures keys are sorted for deterministic output.

    Args:
        data: Dictionary to serialize

    Returns:
        Deterministically serialized bytes

    Examples:
        >>> metadata = {"z": 3, "a": 1, "m": 2}
        >>> bytes_data = serialize_dict_for_capture(metadata)
        >>> # Keys are sorted: {"a": 1, "m": 2, "z": 3}
    """
    return json.dumps(
        data, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
