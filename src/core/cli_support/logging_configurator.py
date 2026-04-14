"""LoggingConfigurator service for configuring logging based on AppConfig.

This module provides the LoggingConfigurator class that handles:
- Logging configuration from AppConfig (level, file path, colors)
- Timestamp suffix application to log and capture file paths
- PID suffix application (legacy name, now applies timestamps)

Validates Requirements: 4.1, 4.2, 4.3, 4.4
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.config.app_config import AppConfig

# Import the actual logging configuration function
from src.core.app.constants.logging_constants import TRACE_LEVEL
from src.core.common.logging_utils import configure_logging_with_environment_tagging


def resolve_stdlib_log_level(level_name: str) -> int:
    """Map config/CLI log level names to numeric stdlib logging levels.

    Python's :mod:`logging` does not define ``TRACE``; the proxy uses a custom
    level (see :data:`TRACE_LEVEL`) so ``LogLevel.TRACE`` can enable TRACE logs.
    """

    name = str(level_name).upper().strip()
    if name == "TRACE":
        return TRACE_LEVEL
    return int(getattr(logging, name))


# Pattern to detect already-suffixed paths (YYYYMMDD_HHMM[SS][-pPID] at end of stem)
TIMESTAMP_SUFFIX_PATTERN = re.compile(r"-\d{8}_\d{4}(?:\d{2})?(?:-p\d+)?$")

logger = logging.getLogger(__name__)


class LoggingConfigurator:
    """Configures logging based on application configuration.

    This service encapsulates all logging configuration functionality including:
    - Setting up log level, file path, and color settings
    - Applying timestamp suffixes to log and capture file paths
    - Handling the PID suffix legacy API (now timestamps)

    Attributes:
        None - stateless service

    Example:
        >>> from src.core.cli_support.logging_configurator import LoggingConfigurator
        >>> configurator = LoggingConfigurator()
        >>> config = configurator.apply_pid_suffixes(config)
        >>> configurator.configure(config)
    """

    def __init__(
        self,
        *,
        configure_fn: Callable[..., None] | None = None,
    ) -> None:
        self._configure_fn = configure_fn

    def configure(self, config: AppConfig) -> None:
        """Configure logging with level, file, and color settings.

        Applies logging configuration from the given AppConfig object,
        setting up handlers for both file and console output as appropriate.

        Args:
            config: Application configuration containing logging settings.

        Raises:
            ValueError: If logging configuration fails (Requirement 4.3).

        Validates: Requirement 4.1 - apply log level, file path, and color settings.
        """
        log_file = config.logging.log_file
        if log_file:
            Path(log_file).expanduser().parent.mkdir(parents=True, exist_ok=True)

        configure_fn = self._configure_fn or configure_logging_with_environment_tagging

        configure_fn(
            level=resolve_stdlib_log_level(config.logging.level.value),
            log_file=log_file,
            use_colors=config.logging.use_colors,
            console_stream=getattr(config.logging, "console_stream", "stderr"),
        )

    def apply_timestamp_suffix(self, path: str | None) -> str | None:
        """Apply timestamp suffix to log file path.

        Appends a timestamp suffix in the format `-YYYYMMDD_HHMMSS-pPID` to the
        filename portion of a path. If the path already has such a suffix,
        returns the original path unchanged to avoid double-suffixing.

        When running under pytest (``PYTEST_CURRENT_TEST`` env var is set), the
        original file stem is replaced with ``pytest`` so that test-generated
        log files are immediately distinguishable from production ones:
        ``proxy-20260414_174601-p261572.log`` → ``pytest-20260414_174601-p261572.log``.

        Args:
            path: The file path to suffix, or None.

        Returns:
            The path with timestamp suffix appended, or None if input was None
            or empty. Returns original path if already suffixed.

        Example:
            >>> configurator = LoggingConfigurator()
            >>> configurator.apply_timestamp_suffix("logs/proxy.log")
            'logs/proxy-20251212_143045-p12345.log'

        Validates: Requirement 4.2 - timestamp suffixes applied consistently.
        """
        if not path:
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pid = os.getpid()
        p = Path(path)

        # Check if already has a timestamp-like suffix to avoid double appending
        if TIMESTAMP_SUFFIX_PATTERN.search(p.stem):
            return str(p)

        # Under pytest, replace the file stem with 'pytest' so test log files
        # are distinguishable from production ones at a glance.
        stem = "pytest" if os.getenv("PYTEST_CURRENT_TEST") else p.stem
        new_name = f"{stem}-{timestamp}-p{pid}{p.suffix}"
        return str(p.with_name(new_name))

    def apply_pid_suffixes(self, config: AppConfig) -> AppConfig:
        """Return config with timestamp-suffixed log and capture files.

        This method applies timestamp suffixes to both log_file and capture_file
        paths in the configuration. The method name is kept as `apply_pid_suffixes`
        for backward compatibility, but the implementation uses timestamps.

        Args:
            config: Application configuration to update.

        Returns:
            A new AppConfig with timestamp-suffixed log and capture file paths.
            Returns the original config unchanged if no updates needed.

        Validates: Requirement 4.2 - consistent timestamp suffix application.
        """
        updated_logging: dict[str, Any] = {}

        # Apply timestamp suffix to log_file
        new_log = self.apply_timestamp_suffix(config.logging.log_file)
        if new_log != config.logging.log_file:
            updated_logging["log_file"] = new_log

        # Apply timestamp suffix to capture_file if present
        current_capture = getattr(config.logging, "capture_file", None)
        new_capture = self.apply_timestamp_suffix(current_capture)
        if new_capture != current_capture:
            updated_logging["capture_file"] = new_capture

        # If no updates needed, return original config
        if not updated_logging:
            return config

        # Create new config with updated logging
        new_logging = config.logging.model_copy(update=updated_logging)
        return config.model_copy(update={"logging": new_logging})
