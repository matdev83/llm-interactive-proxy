"""Unit tests for LoggingApplicator.

Test-Driven Development: Write tests first (RED), then implement (GREEN).

Requirements:
- 6.1: ConfigurationApplicator delegates to domain-specific applicators
- 6.2: Each domain applicator only modifies its relevant configuration section
- 9.1: Unit tests for each domain applicator
"""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest import mock

import pytest
from src.core.cli_support.protocols import CliArgs, CliOverrides
from src.core.config.app_config import LogLevel
from src.core.config.parameter_resolution import ParameterResolution, ParameterSource


class TestLoggingApplicator:
    """Unit tests for LoggingApplicator class."""

    @pytest.fixture
    def applicator(self):
        """Create a LoggingApplicator instance."""
        from src.core.cli_support.applicators.logging_applicator import (
            LoggingApplicator,
        )

        return LoggingApplicator()

    @pytest.fixture
    def empty_args(self) -> CliArgs:
        """Create empty CLI arguments namespace."""
        return argparse.Namespace(
            log_file=None,
            log_level=None,
            log_use_colors=None,
            capture_file=None,
            capture_max_bytes=None,
            capture_truncate_bytes=None,
            capture_max_files=None,
            capture_rotate_interval_seconds=None,
            capture_total_max_bytes=None,
            cbor_capture_dir=None,
            cbor_capture_session_id=None,
        )

    @pytest.fixture
    def overrides(self) -> CliOverrides:
        """Create empty overrides dictionary."""
        return {}

    @pytest.fixture
    def resolution(self) -> ParameterResolution:
        """Create parameter resolution tracker."""
        return ParameterResolution()

    def test_apply_log_file(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that log_file argument is applied correctly."""
        with mock.patch.object(Path, "mkdir"):
            empty_args.log_file = "./logs/proxy.log"
            applicator.apply(empty_args, overrides, resolution)

            assert "logging" in overrides
            log_path = overrides["logging"].get("log_file")
            assert log_path is not None
            assert resolution.is_set("logging.log_file")
            cli_params = resolution.latest_by_source(ParameterSource.CLI)
            assert "logging.log_file" in cli_params

    def test_apply_log_level(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that log_level argument is applied correctly."""
        empty_args.log_level = "DEBUG"
        applicator.apply(empty_args, overrides, resolution)

        assert "logging" in overrides
        assert overrides["logging"].get("level") == LogLevel.DEBUG
        assert resolution.is_set("logging.level")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "logging.level" in cli_params

    def test_apply_log_use_colors(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that log_use_colors argument is applied correctly."""
        empty_args.log_use_colors = True
        applicator.apply(empty_args, overrides, resolution)

        assert "logging" in overrides
        assert overrides["logging"].get("use_colors") is True
        assert resolution.is_set("logging.use_colors")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "logging.use_colors" in cli_params

    def test_apply_capture_file(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that capture_file argument is applied correctly."""
        empty_args.capture_file = "./var/captures/wire.log"
        applicator.apply(empty_args, overrides, resolution)

        assert "logging" in overrides
        assert overrides["logging"].get("capture_file") == "./var/captures/wire.log"
        assert resolution.is_set("logging.capture_file")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "logging.capture_file" in cli_params

    def test_apply_capture_max_bytes(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that capture_max_bytes argument is applied correctly."""
        empty_args.capture_max_bytes = 10485760  # 10MB
        applicator.apply(empty_args, overrides, resolution)

        assert "logging" in overrides
        assert overrides["logging"].get("capture_max_bytes") == 10485760
        assert resolution.is_set("logging.capture_max_bytes")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "logging.capture_max_bytes" in cli_params

    def test_apply_capture_truncate_bytes(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that capture_truncate_bytes argument is applied correctly."""
        empty_args.capture_truncate_bytes = 4096
        applicator.apply(empty_args, overrides, resolution)

        assert "logging" in overrides
        assert overrides["logging"].get("capture_truncate_bytes") == 4096

    def test_apply_capture_max_files(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that capture_max_files argument is applied correctly."""
        empty_args.capture_max_files = 5
        applicator.apply(empty_args, overrides, resolution)

        assert "logging" in overrides
        assert overrides["logging"].get("capture_max_files") == 5

    def test_apply_capture_rotate_interval(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that capture_rotate_interval_seconds argument is applied correctly."""
        empty_args.capture_rotate_interval_seconds = 3600
        applicator.apply(empty_args, overrides, resolution)

        assert "logging" in overrides
        assert overrides["logging"].get("capture_rotate_interval_seconds") == 3600

    def test_apply_capture_total_max_bytes(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that capture_total_max_bytes argument is applied correctly."""
        empty_args.capture_total_max_bytes = 104857600  # 100MB
        applicator.apply(empty_args, overrides, resolution)

        assert "logging" in overrides
        assert overrides["logging"].get("capture_total_max_bytes") == 104857600

    def test_apply_cbor_capture_dir(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that cbor_capture_dir argument is applied correctly."""
        empty_args.cbor_capture_dir = "./var/cbor_captures"
        applicator.apply(empty_args, overrides, resolution)

        assert "logging" in overrides
        assert overrides["logging"].get("cbor_capture_dir") == "./var/cbor_captures"
        assert resolution.is_set("logging.cbor_capture_dir")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "logging.cbor_capture_dir" in cli_params

    def test_apply_cbor_capture_session_id(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that cbor_capture_session_id argument is applied correctly."""
        empty_args.cbor_capture_session_id = "test-session-123"
        applicator.apply(empty_args, overrides, resolution)

        assert "logging" in overrides
        assert overrides["logging"].get("cbor_capture_session_id") == "test-session-123"

    def test_no_modifications_when_all_none(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that no modifications are made when all arguments are None."""
        applicator.apply(empty_args, overrides, resolution)

        # No logging overrides should be added
        assert "logging" not in overrides

    def test_only_modifies_logging_domain(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that applicator only modifies logging-related keys (Property 3: Domain Applicator Isolation)."""
        with mock.patch.object(Path, "mkdir"):
            empty_args.log_file = "./logs/test.log"
            empty_args.log_level = "INFO"
            empty_args.capture_file = "./var/captures/wire.log"
            empty_args.cbor_capture_dir = "./var/cbor"

            applicator.apply(empty_args, overrides, resolution)

            # Only logging key should be present at top level
            for key in overrides:
                assert (
                    key == "logging"
                ), f"LoggingApplicator modified unexpected key: {key}"
