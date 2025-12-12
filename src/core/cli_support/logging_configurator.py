# Copyright 2025 Anthropic
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""LoggingConfigurator service for configuring logging based on AppConfig.

This module provides the LoggingConfigurator class that handles:
- Logging configuration from AppConfig (level, file path, colors)
- Timestamp suffix application to log and capture file paths
- PID suffix application (legacy name, now applies timestamps)

Validates Requirements: 4.1, 4.2, 4.3, 4.4
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.config.app_config import AppConfig

# Import the actual logging configuration function
from src.core.common.logging_utils import configure_logging_with_environment_tagging

# Pattern to detect already-suffixed paths (YYYYMMDD_HHMM at end of stem)
TIMESTAMP_SUFFIX_PATTERN = re.compile(r"-\d{8}_\d{4}$")

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
        configure_logging_with_environment_tagging(
            level=getattr(logging, config.logging.level.value),
            log_file=config.logging.log_file,
            use_colors=config.logging.use_colors,
        )

    def apply_timestamp_suffix(self, path: str | None) -> str | None:
        """Apply timestamp suffix to log file path.

        Appends a timestamp suffix in the format `-YYYYMMDD_HHMM` to the
        filename portion of a path. If the path already has such a suffix,
        returns the original path unchanged to avoid double-suffixing.

        Args:
            path: The file path to suffix, or None.

        Returns:
            The path with timestamp suffix appended, or None if input was None
            or empty. Returns original path if already suffixed.

        Example:
            >>> configurator = LoggingConfigurator()
            >>> configurator.apply_timestamp_suffix("logs/proxy.log")
            'logs/proxy-20251212_1430.log'

        Validates: Requirement 4.2 - timestamp suffixes applied consistently.
        """
        if not path:
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        p = Path(path)

        # Check if already has a timestamp-like suffix to avoid double appending
        if TIMESTAMP_SUFFIX_PATTERN.search(p.stem):
            return str(p)

        new_name = f"{p.stem}-{timestamp}{p.suffix}"
        return str(p.with_name(new_name))

    def apply_pid_suffixes(self, cfg: AppConfig) -> AppConfig:
        """Return config with timestamp-suffixed log and capture files.

        This method applies timestamp suffixes to both log_file and capture_file
        paths in the configuration. The method name is kept as `apply_pid_suffixes`
        for backward compatibility, but the implementation uses timestamps.

        Args:
            cfg: Application configuration to update.

        Returns:
            A new AppConfig with timestamp-suffixed log and capture file paths.
            Returns the original config unchanged if no updates needed.

        Validates: Requirement 4.2 - consistent timestamp suffix application.
        """
        updated_logging: dict[str, Any] = {}

        # Apply timestamp suffix to log_file
        new_log = self.apply_timestamp_suffix(cfg.logging.log_file)
        if new_log != cfg.logging.log_file:
            updated_logging["log_file"] = new_log

        # Apply timestamp suffix to capture_file if present
        current_capture = getattr(cfg.logging, "capture_file", None)
        new_capture = self.apply_timestamp_suffix(current_capture)
        if new_capture != current_capture:
            updated_logging["capture_file"] = new_capture

        # If no updates needed, return original config
        if not updated_logging:
            return cfg

        # Create new config with updated logging
        new_logging = cfg.logging.model_copy(update=updated_logging)
        return cfg.model_copy(update={"logging": new_logging})
