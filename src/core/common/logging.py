"""
Structured logging configuration.

This module provides utilities for configuring and using structured logging.
"""

import logging
import os
import sys
from datetime import datetime
from enum import Enum
from pathlib import Path

import structlog
from structlog.dev import ConsoleRenderer
from structlog.processors import (
    EventRenamer,
    JSONRenderer,
    StackInfoRenderer,
    TimeStamper,
    format_exc_info,
)

from src.core.config_adapter import AppConfig


class LogFormat(str, Enum):
    """Log format options."""
    
    JSON = "json"
    CONSOLE = "console"
    PLAIN = "plain"


def setup_logging(
    config: AppConfig | None = None,
    log_level: str | int | None = None,
    log_format: str | None = None,
    log_file: str | None = None,
) -> None:
    """Set up structured logging.
    
    Args:
        config: Optional application configuration
        log_level: Override log level
        log_format: Override log format
        log_file: Override log file
    """
    # Get configuration
    if config is None:
        config = AppConfig()
        
    # Get log level
    level = log_level or (config.logging.level.value if config.logging is not None else "INFO")
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)
        
    # Get log format
    format_str = log_format or os.environ.get("LOG_FORMAT", "console")
    if format_str not in [e.value for e in LogFormat]:
        format_str = LogFormat.CONSOLE.value
    
    # Get log file
    file_path = log_file or (config.logging.log_file if config.logging is not None else None)
    
    # Configure structlog
    processors: list = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        TimeStamper(fmt="iso"),
        StackInfoRenderer(),
        format_exc_info,
        EventRenamer(to="event"),
    ]
    
    # Add renderer based on format
    if format_str == LogFormat.JSON.value:
        processors.append(JSONRenderer())
    elif format_str == LogFormat.CONSOLE.value:
        processors.append(ConsoleRenderer(colors=sys.stderr.isatty()))
    else:  # PLAIN
        processors.append(structlog.dev.ConsoleRenderer(colors=False))
    
    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    # Set up Python's standard logging
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    
    # Add file handler if log file is specified
    if file_path:
        try:
            # Ensure directory exists
            log_dir = Path(file_path).parent
            log_dir.mkdir(parents=True, exist_ok=True)
            
            file_handler = logging.FileHandler(file_path)
            handlers.append(file_handler)
        except Exception as e:
            # Log to console if file logging fails
            console_logger = logging.getLogger(__name__)
            console_logger.error(f"Failed to set up file logging: {e}")
    
    # Configure the root logger
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=handlers,
    )
    
    # Get the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Set log levels for specific loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    
    # Log startup info
    logger = get_logger()
    logger.info("Logging configured", 
                level=level, 
                format=format_str, 
                file=file_path,
                env=os.environ.get("ENVIRONMENT", "development"))


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a structured logger.
    
    Args:
        name: Optional logger name
        
    Returns:
        A structured logger
    """
    return structlog.get_logger(name)


class LoggingMiddleware:
    """Middleware for logging requests and responses."""
    
    def __init__(
        self,
        request_logging: bool = True,
        response_logging: bool = False,
    ):
        """Initialize the middleware.
        
        Args:
            request_logging: Whether to log requests
            response_logging: Whether to log responses
        """
        self.request_logging = request_logging
        self.response_logging = response_logging
        self.logger = get_logger("api")
    
    async def __call__(self, request, call_next):
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
            self.logger.info(
                "Request received",
                method=method,
                url=url,
                client=client,
            )
            
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
