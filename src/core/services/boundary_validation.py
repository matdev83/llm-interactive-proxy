"""Boundary validation utilities for structured logging and error handling.

This module provides helper functions for consistent boundary validation
logging with correlation identifiers across all boundary surfaces.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.common.contract_serialization import serialize_for_logging
from src.core.domain.request_context import RequestContext


def extract_correlation_ids(
    context: RequestContext | None,
) -> dict[str, str | None]:
    """Extract correlation identifiers from request context.

    Supports both RequestContext (core) and ConnectorRequestContext (connector boundary).
    Uses duck typing to extract request_id and session_id from either type.

    Args:
        context: Request context to extract identifiers from, or None.
            Can be RequestContext or ConnectorRequestContext (or any object with
            request_id and session_id attributes).

    Returns:
        Dictionary with request_id and session_id (may be None)
    """
    if context is None:
        return {"request_id": None, "session_id": None}

    # Duck typing: extract from any object with request_id and session_id attributes
    return {
        "request_id": getattr(context, "request_id", None),
        "session_id": getattr(context, "session_id", None),
    }


def log_boundary_validation_failure(
    logger: logging.Logger,
    message: str,
    context: RequestContext | None,
    service: str,
    violation_type: str,
    details: dict[str, Any],
) -> None:
    """Log boundary validation failure with correlation identifiers.

    Emits a structured warning log with correlation identifiers (request_id,
    session_id) and violation details. Details are redacted to prevent secret
    leakage per NFR4.2.

    Args:
        logger: Logger instance to use for logging
        message: Human-readable error message
        context: Request context for correlation identifiers, or None
        service: Name of the service/component performing validation
        violation_type: Type of boundary violation (e.g., "dict_input", "invalid_type")
        details: Additional violation details to include in log (will be redacted)
    """
    correlation_ids = extract_correlation_ids(context)

    # Redact details to prevent secret leakage (NFR4.2)
    # Details might contain contract data, so serialize with redaction
    redacted_details_str = serialize_for_logging(details, redact=True)
    try:
        import json

        redacted_details = json.loads(redacted_details_str)
    except (TypeError, ValueError):
        # Fallback: use original details if serialization fails
        redacted_details = details

    logger.warning(
        f"Boundary validation failed: {message}",
        extra={
            "request_id": correlation_ids["request_id"],
            "session_id": correlation_ids["session_id"],
            "service": service,
            "violation_type": violation_type,
            "details": redacted_details,
        },
        exc_info=False,  # Don't include stack trace for deterministic validation errors
    )
