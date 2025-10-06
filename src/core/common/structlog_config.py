"""
Structured logging configuration.

This module provides utilities for configuring and using structured logging.
"""

from enum import Enum

import structlog


class LogFormat(str, Enum):
    """Log format options."""

    JSON = "json"
    CONSOLE = "console"
    PLAIN = "plain"


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a structured logger.

    Args:
        name: Optional logger name

    Returns:
        A structured logger
    """
    return structlog.get_logger(name)  # type: ignore
