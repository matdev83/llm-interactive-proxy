"""Logging Applicator - Extracts and applies logging-related CLI arguments.

This applicator handles:
- log_file, log_level, log_use_colors
- capture_file, capture_max_bytes, capture_truncate_bytes
- capture_max_files, capture_rotate_interval_seconds, capture_total_max_bytes
- cbor_capture_dir, cbor_capture_session_id

Requirements satisfied:
- 6.1: ConfigurationApplicator delegates to domain-specific applicators
- 6.2: Each domain applicator only modifies its relevant configuration section
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.cli_support.protocols import CliArgs, CliOverrides
    from src.core.config.parameter_resolution import ParameterResolution

from src.core.config.app_config import LogLevel
from src.core.config.parameter_resolution import ParameterSource


class LoggingApplicator:
    """Applies logging-related CLI arguments to configuration.

    Handles:
    - log_file: Log file path
    - log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    - log_use_colors: Enable/disable colored logging
    - capture_file: Wire capture file path
    - capture_*: Various capture settings
    - cbor_capture_*: CBOR byte-precise capture settings
    """

    def apply(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply logging-related CLI arguments to configuration overrides.

        Args:
            args: Parsed command-line arguments namespace
            overrides: Dictionary to collect configuration overrides
            resolution: Parameter resolution tracker for recording sources
        """
        logging_overrides: dict[str, Any] = {}

        self._apply_log_file(args, logging_overrides, resolution)
        self._apply_log_level(args, logging_overrides, resolution)
        self._apply_log_colors(args, logging_overrides, resolution)
        self._apply_capture_file(args, logging_overrides, resolution)
        self._apply_capture_settings(args, logging_overrides, resolution)
        self._apply_cbor_capture(args, logging_overrides, resolution)

        # Add logging overrides to main overrides if any
        if logging_overrides:
            overrides["logging"] = logging_overrides

    def _apply_log_file(
        self,
        args: CliArgs,
        logging_overrides: dict[str, Any],
        resolution: ParameterResolution,
    ) -> None:
        """Apply log_file argument."""
        if getattr(args, "log_file", None) is not None:
            log_path = str(Path(str(args.log_file)).expanduser())
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            logging_overrides["log_file"] = log_path
            resolution.record(
                "logging.log_file", log_path, ParameterSource.CLI, origin="--log"
            )

    def _apply_log_level(
        self,
        args: CliArgs,
        logging_overrides: dict[str, Any],
        resolution: ParameterResolution,
    ) -> None:
        """Apply log_level argument."""
        if getattr(args, "log_level", None) is not None:
            logging_overrides["level"] = LogLevel[args.log_level]
            resolution.record(
                "logging.level",
                LogLevel[args.log_level].value,
                ParameterSource.CLI,
                origin="--log-level",
            )

    def _apply_log_colors(
        self,
        args: CliArgs,
        logging_overrides: dict[str, Any],
        resolution: ParameterResolution,
    ) -> None:
        """Apply log_use_colors argument."""
        if getattr(args, "log_use_colors", None) is not None:
            logging_overrides["use_colors"] = args.log_use_colors
            flag_name = "--log-colors" if args.log_use_colors else "--no-log-colors"
            resolution.record(
                "logging.use_colors",
                args.log_use_colors,
                ParameterSource.CLI,
                origin=flag_name,
            )

    def _apply_capture_file(
        self,
        args: CliArgs,
        logging_overrides: dict[str, Any],
        resolution: ParameterResolution,
    ) -> None:
        """Apply capture_file argument."""
        if getattr(args, "capture_file", None) is not None:
            logging_overrides["capture_file"] = args.capture_file
            resolution.record(
                "logging.capture_file",
                args.capture_file,
                ParameterSource.CLI,
                origin="--capture-file",
            )

    def _apply_capture_settings(
        self,
        args: CliArgs,
        logging_overrides: dict[str, Any],
        resolution: ParameterResolution,
    ) -> None:
        """Apply various capture settings."""
        if getattr(args, "capture_max_bytes", None) is not None:
            logging_overrides["capture_max_bytes"] = args.capture_max_bytes
            resolution.record(
                "logging.capture_max_bytes",
                args.capture_max_bytes,
                ParameterSource.CLI,
                origin="--capture-max-bytes",
            )

        if getattr(args, "capture_truncate_bytes", None) is not None:
            logging_overrides["capture_truncate_bytes"] = args.capture_truncate_bytes
            resolution.record(
                "logging.capture_truncate_bytes",
                args.capture_truncate_bytes,
                ParameterSource.CLI,
                origin="--capture-truncate-bytes",
            )

        if getattr(args, "capture_max_files", None) is not None:
            logging_overrides["capture_max_files"] = args.capture_max_files
            resolution.record(
                "logging.capture_max_files",
                args.capture_max_files,
                ParameterSource.CLI,
                origin="--capture-max-files",
            )

        if getattr(args, "capture_rotate_interval_seconds", None) is not None:
            logging_overrides["capture_rotate_interval_seconds"] = (
                args.capture_rotate_interval_seconds
            )
            resolution.record(
                "logging.capture_rotate_interval_seconds",
                args.capture_rotate_interval_seconds,
                ParameterSource.CLI,
                origin="--capture-rotate-interval",
            )

        if getattr(args, "capture_total_max_bytes", None) is not None:
            logging_overrides["capture_total_max_bytes"] = args.capture_total_max_bytes
            resolution.record(
                "logging.capture_total_max_bytes",
                args.capture_total_max_bytes,
                ParameterSource.CLI,
                origin="--capture-total-max-bytes",
            )

    def _apply_cbor_capture(
        self,
        args: CliArgs,
        logging_overrides: dict[str, Any],
        resolution: ParameterResolution,
    ) -> None:
        """Apply CBOR capture settings."""
        if getattr(args, "cbor_capture_dir", None) is not None:
            logging_overrides["cbor_capture_dir"] = args.cbor_capture_dir
            resolution.record(
                "logging.cbor_capture_dir",
                args.cbor_capture_dir,
                ParameterSource.CLI,
                origin="--cbor-capture-dir",
            )

        if getattr(args, "cbor_capture_session_id", None) is not None:
            logging_overrides["cbor_capture_session_id"] = args.cbor_capture_session_id
            resolution.record(
                "logging.cbor_capture_session_id",
                args.cbor_capture_session_id,
                ParameterSource.CLI,
                origin="--cbor-capture-session",
            )
