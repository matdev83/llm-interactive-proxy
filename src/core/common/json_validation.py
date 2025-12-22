"""JSON validation utilities for DoS protection.

This module provides reusable functions for validating JSON structures
to prevent DoS attacks through deep nesting or massive arrays.
"""

from __future__ import annotations

from typing import Any

# Security limits to prevent DoS attacks
MAX_JSON_DEPTH = 100  # Maximum nesting depth to prevent stack overflow
MAX_ARRAY_ELEMENTS = 1_000_000  # Maximum array elements to prevent memory exhaustion


class JSONValidationError(Exception):
    """Exception raised when JSON validation fails."""


def validate_json_structure(
    data: Any,
    *,
    max_depth: int = MAX_JSON_DEPTH,
    max_array_elements: int = MAX_ARRAY_ELEMENTS,
    depth: int = 0,
) -> None:
    """Validate JSON structure to prevent DoS attacks.

    Checks for:
    - Deep nesting that could cause stack overflow
    - Large arrays that could cause memory exhaustion

    Args:
        data: The JSON data to validate (dict, list, or primitive)
        max_depth: Maximum allowed nesting depth (default: 100)
        max_array_elements: Maximum allowed array elements (default: 1,000,000)
        depth: Current nesting depth (used internally for recursion)

    Raises:
        JSONValidationError: If validation fails (depth exceeded or array too large)
    """
    if depth > max_depth:
        raise JSONValidationError(
            f"JSON nesting depth {depth} exceeds maximum allowed depth of {max_depth}"
        )

    if isinstance(data, dict):
        for value in data.values():
            validate_json_structure(
                value,
                max_depth=max_depth,
                max_array_elements=max_array_elements,
                depth=depth + 1,
            )
    elif isinstance(data, list):
        if len(data) > max_array_elements:
            raise JSONValidationError(
                f"JSON array size {len(data)} exceeds maximum allowed elements of {max_array_elements}"
            )
        for item in data:
            validate_json_structure(
                item,
                max_depth=max_depth,
                max_array_elements=max_array_elements,
                depth=depth + 1,
            )
