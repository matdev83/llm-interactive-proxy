"""Unit tests for LoggingConfigurator.

Tests the LoggingConfigurator service that handles:
- Logging configuration from AppConfig
- Timestamp suffix application to log/capture files
- PID suffix application (renamed to timestamp suffix internally)

Validates Requirements: 4.1, 4.2, 4.3, 4.4
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

if TYPE_CHECKING:
    pass


class TestApplyTimestampSuffix:
    """Tests for apply_timestamp_suffix method.

    Validates: Requirement 4.2 - timestamp suffixes applied consistently.
    """

    def test_none_path_returns_none(self) -> None:
        """GIVEN a None path WHEN apply_timestamp_suffix is called THEN None is returned."""
        from src.core.cli_support.logging_configurator import LoggingConfigurator

        configurator = LoggingConfigurator()
        result = configurator.apply_timestamp_suffix(None)
        assert result is None

    def test_empty_string_path_returns_none(self) -> None:
        """GIVEN an empty string path WHEN apply_timestamp_suffix is called THEN None is returned."""
        from src.core.cli_support.logging_configurator import LoggingConfigurator

        configurator = LoggingConfigurator()
        result = configurator.apply_timestamp_suffix("")
        assert result is None

    def test_simple_path_gets_timestamp_suffix(self) -> None:
        """GIVEN a simple path WHEN apply_timestamp_suffix is called THEN timestamp is appended."""
        from src.core.cli_support.logging_configurator import LoggingConfigurator

        configurator = LoggingConfigurator()
        result = configurator.apply_timestamp_suffix("logs/proxy.log")
        assert result is not None
        # Verify format: stem-YYYYMMDD_HHMMSS-pPID.suffix
        assert re.match(r"logs[\\/]proxy-\d{8}_\d{6}-p\d+\.log$", result)

    def test_path_with_subdirectories(self) -> None:
        """GIVEN a path with subdirectories WHEN apply_timestamp_suffix is called THEN directory preserved."""
        from src.core.cli_support.logging_configurator import LoggingConfigurator

        configurator = LoggingConfigurator()
        result = configurator.apply_timestamp_suffix("var/logs/application.log")
        assert result is not None
        # Directory structure should be preserved
        assert "var" in result or "logs" in result
        assert re.search(r"application-\d{8}_\d{6}-p\d+\.log$", result)

    def test_already_suffixed_path_not_double_suffixed(self) -> None:
        """GIVEN an already-suffixed path WHEN apply_timestamp_suffix is called THEN original returned."""
        from src.core.cli_support.logging_configurator import LoggingConfigurator

        configurator = LoggingConfigurator()
        already_suffixed = "logs/proxy-20251212_1430.log"
        result = configurator.apply_timestamp_suffix(already_suffixed)
        assert result is not None
        # Should return unchanged - no double suffixing (normalize paths for cross-platform)
        assert Path(result) == Path(already_suffixed)

    def test_path_with_no_extension(self) -> None:
        """GIVEN a path without extension WHEN apply_timestamp_suffix is called THEN suffix still applied."""
        from src.core.cli_support.logging_configurator import LoggingConfigurator

        configurator = LoggingConfigurator()
        result = configurator.apply_timestamp_suffix("logs/proxy")
        assert result is not None
        # Should have timestamp but no trailing extension
        assert re.match(r"logs[\\/]proxy-\d{8}_\d{6}-p\d+$", result)

    def test_path_with_multiple_extensions(self) -> None:
        """GIVEN a path with multiple extensions WHEN apply_timestamp_suffix is called THEN only last extension handled."""
        from src.core.cli_support.logging_configurator import LoggingConfigurator

        configurator = LoggingConfigurator()
        result = configurator.apply_timestamp_suffix("logs/capture.log.cbor")
        assert result is not None
        # The .cbor extension should be preserved
        assert result.endswith(".cbor")
        assert re.search(r"-\d{8}_\d{6}-p\d+\.cbor$", result)

    def test_absolute_path_preserved(self) -> None:
        """GIVEN an absolute path WHEN apply_timestamp_suffix is called THEN absolute path returned."""
        from src.core.cli_support.logging_configurator import LoggingConfigurator

        configurator = LoggingConfigurator()
        # Windows-style absolute path
        result = configurator.apply_timestamp_suffix("C:\\var\\logs\\proxy.log")
        assert result is not None
        assert result.startswith("C:")
        assert re.search(r"proxy-\d{8}_\d{6}-p\d+\.log$", result)

    def test_unix_absolute_path_preserved(self) -> None:
        """GIVEN a Unix absolute path WHEN apply_timestamp_suffix is called THEN absolute path returned."""
        import os

        from src.core.cli_support.logging_configurator import LoggingConfigurator

        configurator = LoggingConfigurator()
        result = configurator.apply_timestamp_suffix("/var/logs/proxy.log")
        assert result is not None
        # On Windows, Path normalizes /var to \var, so check platform-appropriately
        result_path = Path(result)
        if os.name == "nt":
            # On Windows, the leading slash becomes something like \var
            assert "var" in str(result_path)
        else:
            assert result.startswith("/")
        assert re.search(r"proxy-\d{8}_\d{6}-p\d+\.log$", result)

    def test_timestamp_format_matches_pattern(self) -> None:
        """GIVEN a path WHEN apply_timestamp_suffix is called THEN timestamp matches YYYYMMDD_HHMMSS-pPID pattern."""
        from src.core.cli_support.logging_configurator import LoggingConfigurator

        configurator = LoggingConfigurator()
        with (
            patch("src.core.cli_support.logging_configurator.datetime") as mock_dt,
            patch("src.core.cli_support.logging_configurator.os.getpid") as mock_getpid,
        ):
            mock_now = MagicMock()
            mock_now.strftime.return_value = "20251212_183045"
            mock_dt.now.return_value = mock_now
            mock_getpid.return_value = 12345

            result = configurator.apply_timestamp_suffix("test.log")
            assert result == "test-20251212_183045-p12345.log"


class TestApplyPidSuffixes:
    """Tests for apply_pid_suffixes method.

    Validates: Requirement 4.2 - consistent timestamp suffix application.
    Note: Method named apply_pid_suffixes for backward compatibility but applies timestamps.
    """

    @pytest.fixture
    def mock_config(self) -> MagicMock:
        """Create a mock AppConfig with logging settings."""
        config = MagicMock()
        config.logging = MagicMock()
        config.logging.log_file = "var/logs/proxy.log"
        config.logging.capture_file = "var/wire_captures/proxy.cbor"
        config.logging.cbor_capture_file = None
        config.logging.level = MagicMock()
        config.logging.level.value = "DEBUG"
        config.logging.use_colors = True
        return config

    def test_applies_suffix_to_log_file(self, mock_config: MagicMock) -> None:
        """GIVEN a config with log_file WHEN apply_pid_suffixes called THEN log_file gets suffix."""
        from src.core.cli_support.logging_configurator import LoggingConfigurator

        configurator = LoggingConfigurator()

        # Setup model_copy to return new config
        new_logging = MagicMock()
        mock_config.logging.model_copy.return_value = new_logging
        new_config = MagicMock()
        mock_config.model_copy.return_value = new_config

        configurator.apply_pid_suffixes(mock_config)

        # Should call model_copy with updated logging
        mock_config.logging.model_copy.assert_called_once()
        mock_config.model_copy.assert_called_once()

    def test_applies_suffix_to_capture_file(self, mock_config: MagicMock) -> None:
        """GIVEN a config with capture_file WHEN apply_pid_suffixes called THEN capture_file gets suffix."""
        from src.core.cli_support.logging_configurator import LoggingConfigurator

        configurator = LoggingConfigurator()
        mock_config.logging.log_file = None  # No log file

        # Set capture_file via getattr behavior
        mock_config.logging.capture_file = "var/captures/wire.cbor"

        new_logging = MagicMock()
        mock_config.logging.model_copy.return_value = new_logging
        new_config = MagicMock()
        mock_config.model_copy.return_value = new_config

        configurator.apply_pid_suffixes(mock_config)
        # Should attempt to update capture_file with timestamp
        mock_config.logging.model_copy.assert_called_once()

    def test_no_update_if_no_files(self, mock_config: MagicMock) -> None:
        """GIVEN a config with no log/capture files WHEN apply_pid_suffixes called THEN config unchanged."""
        from src.core.cli_support.logging_configurator import LoggingConfigurator

        configurator = LoggingConfigurator()
        mock_config.logging.log_file = None
        # Mock getattr to return None for capture_file
        mock_config.logging.capture_file = None

        result = configurator.apply_pid_suffixes(mock_config)
        # Should return original config if no files to suffix
        # Since no updates, should return the original config
        assert result == mock_config

    def test_returns_new_config_with_updated_logging(self) -> None:
        """GIVEN a real AppConfig WHEN apply_pid_suffixes called THEN new config returned with suffixed paths."""
        from src.core.cli_support.logging_configurator import LoggingConfigurator
        from src.core.config.app_config import AppConfig

        config = AppConfig(
            logging={"log_file": "test.log", "level": "DEBUG", "use_colors": True}
        )
        configurator = LoggingConfigurator()

        result = configurator.apply_pid_suffixes(config)

        # Should be a new config instance
        assert result is not config
        # Log file should have timestamp suffix
        assert result.logging.log_file is not None
        assert re.search(r"test-\d{8}_\d{6}-p\d+\.log$", result.logging.log_file)


class TestConfigure:
    """Tests for configure method.

    Validates: Requirement 4.1 - apply log level, file path, and color settings.
    Validates: Requirement 4.4 - injectable logging handlers.
    """

    @pytest.fixture
    def mock_config_for_configure(self) -> MagicMock:
        """Create a mock AppConfig for configure tests."""
        config = MagicMock()
        config.logging = MagicMock()
        config.logging.log_file = "var/logs/proxy.log"
        config.logging.level = MagicMock()
        config.logging.level.value = "DEBUG"
        config.logging.use_colors = True
        config.logging.console_stream = "stderr"
        return config

    def test_configure_calls_logging_setup(
        self, mock_config_for_configure: MagicMock
    ) -> None:
        """GIVEN a config WHEN configure called THEN logging is set up with correct parameters."""
        from src.core.cli_support.logging_configurator import LoggingConfigurator

        configurator = LoggingConfigurator()

        with patch(
            "src.core.cli_support.logging_configurator.configure_logging_with_environment_tagging"
        ) as mock_configure:
            configurator.configure(mock_config_for_configure)

            mock_configure.assert_called_once_with(
                level=logging.DEBUG,
                log_file="var/logs/proxy.log",
                use_colors=True,
                console_stream="stderr",
            )

    def test_configure_respects_log_level(
        self, mock_config_for_configure: MagicMock
    ) -> None:
        """GIVEN different log levels WHEN configure called THEN correct level is used."""
        from src.core.cli_support.logging_configurator import LoggingConfigurator

        # Test with INFO level
        mock_config_for_configure.logging.level.value = "INFO"

        configurator = LoggingConfigurator()

        with patch(
            "src.core.cli_support.logging_configurator.configure_logging_with_environment_tagging"
        ) as mock_configure:
            configurator.configure(mock_config_for_configure)

            mock_configure.assert_called_once_with(
                level=logging.INFO,
                log_file="var/logs/proxy.log",
                use_colors=True,
                console_stream="stderr",
            )

    def test_configure_respects_colors_disabled(
        self, mock_config_for_configure: MagicMock
    ) -> None:
        """GIVEN colors disabled WHEN configure called THEN use_colors is False."""
        from src.core.cli_support.logging_configurator import LoggingConfigurator

        mock_config_for_configure.logging.use_colors = False

        configurator = LoggingConfigurator()

        with patch(
            "src.core.cli_support.logging_configurator.configure_logging_with_environment_tagging"
        ) as mock_configure:
            configurator.configure(mock_config_for_configure)

            mock_configure.assert_called_once_with(
                level=logging.DEBUG,
                log_file="var/logs/proxy.log",
                use_colors=False,
                console_stream="stderr",
            )

    def test_configure_with_no_log_file(
        self, mock_config_for_configure: MagicMock
    ) -> None:
        """GIVEN no log file WHEN configure called THEN None is passed for log_file."""
        from src.core.cli_support.logging_configurator import LoggingConfigurator

        mock_config_for_configure.logging.log_file = None

        configurator = LoggingConfigurator()

        with patch(
            "src.core.cli_support.logging_configurator.configure_logging_with_environment_tagging"
        ) as mock_configure:
            configurator.configure(mock_config_for_configure)

            mock_configure.assert_called_once_with(
                level=logging.DEBUG,
                log_file=None,
                use_colors=True,
                console_stream="stderr",
            )


class TestLogLevelConversion:
    """Tests for log level string to logging constant conversion."""

    def test_all_log_levels_supported(self) -> None:
        """GIVEN all standard log levels WHEN configure called THEN correct constants used."""
        from unittest.mock import MagicMock, patch

        from src.core.cli_support.logging_configurator import LoggingConfigurator

        levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        expected = [
            logging.DEBUG,
            logging.INFO,
            logging.WARNING,
            logging.ERROR,
            logging.CRITICAL,
        ]

        for level_str, expected_level in zip(levels, expected, strict=False):
            config = MagicMock()
            config.logging = MagicMock()
            config.logging.log_file = None
            config.logging.level = MagicMock()
            config.logging.level.value = level_str
            config.logging.use_colors = False

            configurator = LoggingConfigurator()

            with patch(
                "src.core.cli_support.logging_configurator.configure_logging_with_environment_tagging"
            ) as mock_configure:
                configurator.configure(config)
                call_args = mock_configure.call_args
                assert (
                    call_args.kwargs["level"] == expected_level
                ), f"Level {level_str} should map to {expected_level}"


class TestLoggingConfiguratorIntegration:
    """Integration tests for LoggingConfigurator with real AppConfig."""

    def test_full_workflow_with_real_config(self) -> None:
        """GIVEN a real AppConfig WHEN full workflow executed THEN logging configured correctly."""
        from src.core.cli_support.logging_configurator import LoggingConfigurator
        from src.core.config.app_config import AppConfig

        config = AppConfig(
            logging={
                "log_file": "var/logs/integration.log",
                "level": "INFO",
                "use_colors": True,
            }
        )

        configurator = LoggingConfigurator()

        # First apply pid suffixes (timestamps)
        timestamped_config = configurator.apply_pid_suffixes(config)

        # Verify timestamp was applied
        assert timestamped_config.logging.log_file is not None
        assert re.search(
            r"integration-\d{8}_\d{6}-p\d+\.log$",
            timestamped_config.logging.log_file,
        )

        # Then configure logging (with mock to avoid side effects)
        with patch(
            "src.core.cli_support.logging_configurator.configure_logging_with_environment_tagging"
        ) as mock_configure:
            configurator.configure(timestamped_config)

            mock_configure.assert_called_once()
            call_kwargs = mock_configure.call_args.kwargs
            assert call_kwargs["level"] == logging.INFO
            assert "integration-" in call_kwargs["log_file"]
            assert call_kwargs["use_colors"] is True


class TestTimestampSuffixEdgeCases:
    """Edge case tests for timestamp suffix handling."""

    def test_very_long_filename(self) -> None:
        """GIVEN a very long filename WHEN apply_timestamp_suffix called THEN suffix still applied."""
        from src.core.cli_support.logging_configurator import LoggingConfigurator

        configurator = LoggingConfigurator()
        long_name = "a" * 200 + ".log"
        result = configurator.apply_timestamp_suffix(long_name)
        assert result is not None
        assert re.search(r"-\d{8}_\d{6}-p\d+\.log$", result)

    def test_special_characters_in_path(self) -> None:
        """GIVEN path with special chars WHEN apply_timestamp_suffix called THEN handled correctly."""
        from src.core.cli_support.logging_configurator import LoggingConfigurator

        configurator = LoggingConfigurator()
        result = configurator.apply_timestamp_suffix("logs/my-special_file.log")
        assert result is not None
        assert re.search(r"my-special_file-\d{8}_\d{6}-p\d+\.log$", result)

    def test_path_with_dots_in_directory(self) -> None:
        """GIVEN path with dots in directory names WHEN apply_timestamp_suffix called THEN handled correctly."""
        from src.core.cli_support.logging_configurator import LoggingConfigurator

        configurator = LoggingConfigurator()
        result = configurator.apply_timestamp_suffix("./var/logs/proxy.log")
        assert result is not None
        assert re.search(r"proxy-\d{8}_\d{6}-p\d+\.log$", result)

    def test_cbor_capture_file_extension(self) -> None:
        """GIVEN a CBOR capture file WHEN apply_timestamp_suffix called THEN .cbor extension preserved."""
        from src.core.cli_support.logging_configurator import LoggingConfigurator

        configurator = LoggingConfigurator()
        result = configurator.apply_timestamp_suffix("var/wire_captures/proxy.cbor")
        assert result is not None
        assert result.endswith(".cbor")
        assert re.search(r"proxy-\d{8}_\d{6}-p\d+\.cbor$", result)


class TestResolveStdlibLogLevel:
    """TRACE is not a stdlib logging module attribute; map it to the project constant."""

    def test_trace_maps_to_trace_level_constant(self) -> None:
        from src.core.app.constants.logging_constants import TRACE_LEVEL
        from src.core.cli_support.logging_configurator import resolve_stdlib_log_level

        assert resolve_stdlib_log_level("TRACE") == TRACE_LEVEL

    def test_debug_maps_to_logging_debug(self) -> None:
        from src.core.cli_support.logging_configurator import resolve_stdlib_log_level

        assert resolve_stdlib_log_level("DEBUG") == logging.DEBUG
