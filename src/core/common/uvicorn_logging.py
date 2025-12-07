from __future__ import annotations

from typing import Any


def get_uvicorn_logging_config(use_colors: bool = False) -> dict[str, Any]:
    """
    Generate Uvicorn logging configuration.

    Args:
        use_colors: Whether to enable colored output in Uvicorn logs.

    Returns:
        Uvicorn logging configuration dictionary.
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": "%(levelprefix)s %(asctime)s - %(message)s",
                "use_colors": use_colors,
            },
            "access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
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
