from __future__ import annotations

import logging
from typing import Any

from src.core.common.logging_utils import _get_environment_tag


class UvicornEnvironmentTaggingFormatter(logging.Formatter):
    """Custom formatter for Uvicorn that adds environment tags like the main app.

    This ensures Uvicorn log messages match the format of the rest of the application:
    YYYY-MM-DD HH:MM:SS,mmm [LEVEL] [env] [pid=XXX] name:lineno message
    """

    def __init__(
        self,
        fmt: str | None = None,
        datefmt: str | None = None,
        use_colors: bool = False,
    ) -> None:
        # Use project-standard format if none provided - compact level, env tag, and PID
        if fmt is None:
            fmt = "%(asctime)s [%(levelname)s] [%(env_tag)s] [pid=%(process)d] %(name)s:%(lineno)d %(message)s"
        super().__init__(fmt, datefmt)
        self._env_tag = _get_environment_tag()
        self._use_colors = use_colors

    def format(self, record: logging.LogRecord) -> str:
        """Add environment tag to the log record before formatting."""
        record.env_tag = self._env_tag
        return super().format(record)


def get_uvicorn_logging_config(use_colors: bool = False) -> dict[str, Any]:
    """
    Generate Uvicorn logging configuration.

    The configuration uses a custom formatter that matches the application's
    log format, ensuring consistent output across all log messages.

    Args:
        use_colors: Whether to enable colored output in Uvicorn logs.
                    Note: Colors are not currently implemented in the custom
                    formatter but the parameter is preserved for API compatibility.

    Returns:
        Uvicorn logging configuration dictionary.
    """
    # Use project-standard log format matching EnvironmentTaggingFormatter in logging_utils.py
    # Compact level (no padding), env tag, and PID
    standard_fmt = "%(asctime)s [%(levelname)s] [%(env_tag)s] [pid=%(process)d] %(name)s:%(lineno)d %(message)s"
    # For access logs, include client address and request info
    access_fmt = (
        "%(asctime)s [%(levelname)s] [%(env_tag)s] [pid=%(process)d] %(name)s:%(lineno)d "
        '%(client_addr)s - "%(request_line)s" %(status_code)s'
    )

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": "src.core.common.uvicorn_logging.UvicornEnvironmentTaggingFormatter",
                "fmt": standard_fmt,
                "use_colors": use_colors,
            },
            "access": {
                "()": "src.core.common.uvicorn_logging.UvicornEnvironmentTaggingFormatter",
                "fmt": access_fmt,
                "use_colors": use_colors,
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
            },
            "access": {
                "formatter": "access",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"level": "INFO"},
            "uvicorn.access": {"handlers": [], "level": "INFO", "propagate": False},
        },
    }


# Backward compatibility for existing imports
UVICORN_LOGGING_CONFIG = get_uvicorn_logging_config(use_colors=False)
