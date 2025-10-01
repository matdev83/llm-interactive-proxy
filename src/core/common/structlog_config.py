"""
Structured logging configuration.

This module provides utilities for configuring and using structured logging.
"""

from datetime import datetime
from enum import Enum
from typing import Any

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


class LoggingMiddleware:
    """Middleware for logging requests and responses."""

    def __init__(self, request_logging: bool = True, response_logging: bool = False):
        """Initialize the middleware.

        Args:
            request_logging: Whether to log requests
            response_logging: Whether to log responses
        """
        self.request_logging = request_logging
        self.response_logging = response_logging
        self.logger = get_logger("api")

    async def __call__(self, request: Any, call_next: Any) -> Any:
        """Process the request.

        Args:
            request: The request to process
            call_next: The next middleware to call

        Returns:
            The response
        """
        start_time = datetime.now()

        # Log request
        if self.request_logging:
            # Extract details
            url = str(request.url)
            method = request.method
            client = request.client.host if request.client else "unknown"

            # Log before processing
            self.logger.info("Request received", method=method, url=url, client=client)

        try:
            # Process request
            response = await call_next(request)

            # Log response
            if self.response_logging:
                duration = datetime.now() - start_time
                status_code = response.status_code

                self.logger.info(
                    "Response sent",
                    status_code=status_code,
                    duration_ms=duration.total_seconds() * 1000,
                )

            return response

        except Exception as e:
            # Log exception
            duration = datetime.now() - start_time

            self.logger.error(
                "Request failed",
                error=str(e),
                error_type=type(e).__name__,
                duration_ms=duration.total_seconds() * 1000,
                exc_info=True,
            )

            # Re-raise the exception
            raise
