"""
Structured logging configuration.

This module provides utilities for configuring and using structured logging.
"""

from enum import Enum

import structlog

from src.core.common.logging_utils import CompatibleBoundLogger


class LogFormat(str, Enum):
    """Log format options."""

    JSON = "json"
    CONSOLE = "console"
    PLAIN = "plain"


def get_logger(name: str | None = None) -> CompatibleBoundLogger:
    """Get a structured logger.

    Args:
        name: Optional logger name

    Returns:
        A structured logger
    """
    return CompatibleBoundLogger(structlog.get_logger(name))
