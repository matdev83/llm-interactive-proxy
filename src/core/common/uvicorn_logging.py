from __future__ import annotations

import logging
from typing import Any

from src.core.common.logging_utils import format_log_pid_short


class UvicornEnvironmentTaggingFormatter(logging.Formatter):
    """Custom formatter for Uvicorn aligned with the main app log layout.

    Format matches :class:`EnvironmentTaggingFormatter` defaults:
    ``YYYY-MM-DD HH:MM:SS,mmm [LEVEL] [pid=*XXXX] name:lineno message``.
    """

    def __init__(
        self,
        fmt: str | None = None,
        datefmt: str | None = None,
        use_colors: bool = False,
    ) -> None:
        if fmt is None:
            fmt = "%(asctime)s [%(levelname)s] [pid=%(pid_short)s] %(name)s:%(lineno)d %(message)s"
        super().__init__(fmt, datefmt)
        self._use_colors = use_colors

    def format(self, record: logging.LogRecord) -> str:
        """Set ``pid_short`` and optional Uvicorn access fields before formatting."""
        record.pid_short = format_log_pid_short(getattr(record, "process", None))
        if not hasattr(record, "client_addr"):
            self._maybe_populate_access_fields(record)
        return super().format(record)

    @staticmethod
    def _maybe_populate_access_fields(record: logging.LogRecord) -> None:
        if record.name != "uvicorn.access":
            return
        args = record.args
        if not isinstance(args, tuple) or len(args) < 5:
            return
        client_addr, method, path, http_version, status_code = args[:5]
        record.client_addr = client_addr
        record.request_line = f"{method} {path} HTTP/{http_version}"
        record.status_code = status_code


def get_uvicorn_logging_config(
    use_colors: bool = False,
    *,
    log_level: str = "INFO",
    log_file: str | None = None,
    console_stream: str = "stderr",
) -> dict[str, Any]:
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
    standard_fmt = "%(asctime)s [%(levelname)s] [pid=%(pid_short)s] %(name)s:%(lineno)d %(message)s"
    access_fmt = (
        "%(asctime)s [%(levelname)s] [pid=%(pid_short)s] %(name)s:%(lineno)d "
        '%(client_addr)s - "%(request_line)s" %(status_code)s'
    )

    level_text = str(log_level).upper()
    valid_levels = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}
    level = level_text if level_text in valid_levels else "INFO"
    stream_name = str(console_stream or "stderr").strip().lower()
    use_stdout = stream_name == "stdout"

    config: dict[str, Any] = {
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
                "stream": "ext://sys.stdout" if use_stdout else "ext://sys.stderr",
            },
            "access": {
                "formatter": "access",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout" if use_stdout else "ext://sys.stderr",
            },
        },
        "loggers": {
            "uvicorn": {
                "handlers": ["default"],
                "level": level,
                "propagate": False,
            },
            "uvicorn.error": {
                "handlers": ["default"],
                "level": level,
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": ["access"],
                "level": level,
                "propagate": False,
            },
        },
    }

    if log_file:
        config["handlers"]["file"] = {
            "formatter": "default",
            "class": "logging.FileHandler",
            "filename": log_file,
        }
        config["loggers"]["uvicorn"]["handlers"].append("file")
        config["loggers"]["uvicorn.error"]["handlers"].append("file")
        config["loggers"]["uvicorn.access"]["handlers"].append("file")

    return config


# Backward compatibility for existing imports
UVICORN_LOGGING_CONFIG = get_uvicorn_logging_config(use_colors=False, log_level="INFO")
