"""Unit tests for AccessModeApplicator.

Test-Driven Development: Write tests first (RED), then implement (GREEN).

Requirements:
- 1.2: CLI flag --single-user-mode sets mode to SINGLE_USER
- 1.3: CLI flag --multi-user-mode sets mode to MULTI_USER
- 1.1: No flags defaults to SINGLE_USER
- 3.3: Parameter resolution tracking works correctly
"""

from __future__ import annotations

import argparse

import pytest
from src.core.cli_support.protocols import CliArgs, CliOverrides
from src.core.config.models.access_mode import AccessMode
from src.core.config.parameter_resolution import ParameterResolution, ParameterSource


class TestAccessModeApplicator:
    """Unit tests for AccessModeApplicator class."""

    @pytest.fixture
    def applicator(self):
        """Create an AccessModeApplicator instance."""
        from src.core.cli_support.applicators.access_mode_applicator import (
            AccessModeApplicator,
        )

        return AccessModeApplicator()

    @pytest.fixture
    def empty_args(self) -> CliArgs:
        """Create empty CLI arguments namespace."""
        return argparse.Namespace(
            single_user_mode=False,
            multi_user_mode=False,
        )

    @pytest.fixture
    def overrides(self) -> CliOverrides:
        """Create empty overrides dictionary."""
        return {}

    @pytest.fixture
    def resolution(self) -> ParameterResolution:
        """Create parameter resolution tracker."""
        return ParameterResolution()

    def test_apply_single_user_mode_flag(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that --single-user-mode flag sets mode to SINGLE_USER."""
        empty_args.single_user_mode = True
        empty_args.multi_user_mode = False

        applicator.apply(empty_args, overrides, resolution)

        access_mode_override = overrides.get("access_mode", {})
        assert isinstance(access_mode_override, dict)
        assert access_mode_override.get("mode") == AccessMode.SINGLE_USER
        assert resolution.is_set("access_mode.mode")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "access_mode.mode" in cli_params
        assert cli_params["access_mode.mode"].origin == "--single-user-mode"

    def test_apply_multi_user_mode_flag(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that --multi-user-mode flag sets mode to MULTI_USER."""
        empty_args.single_user_mode = False
        empty_args.multi_user_mode = True

        applicator.apply(empty_args, overrides, resolution)

        access_mode_override = overrides.get("access_mode", {})
        assert isinstance(access_mode_override, dict)
        assert access_mode_override.get("mode") == AccessMode.MULTI_USER
        assert resolution.is_set("access_mode.mode")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "access_mode.mode" in cli_params
        assert cli_params["access_mode.mode"].origin == "--multi-user-mode"

    def test_defaults_to_single_user_when_no_flags(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that no flags defaults to SINGLE_USER mode."""
        empty_args.single_user_mode = False
        empty_args.multi_user_mode = False

        applicator.apply(empty_args, overrides, resolution)

        access_mode_override = overrides.get("access_mode", {})
        assert isinstance(access_mode_override, dict)
        assert access_mode_override.get("mode") == AccessMode.SINGLE_USER
        assert resolution.is_set("access_mode.mode")
        default_params = resolution.latest_by_source(ParameterSource.DEFAULT)
        assert "access_mode.mode" in default_params
        assert default_params["access_mode.mode"].origin == "default"

    def test_cli_flag_overrides_config_file_value(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that CLI flag overrides any existing config file value."""
        # Simulate config file already set multi_user_mode
        overrides["access_mode"] = {"mode": AccessMode.MULTI_USER}

        # CLI flag sets single_user_mode
        empty_args.single_user_mode = True
        empty_args.multi_user_mode = False

        applicator.apply(empty_args, overrides, resolution)

        # CLI should override config
        access_mode_override = overrides.get("access_mode", {})
        assert isinstance(access_mode_override, dict)
        assert access_mode_override.get("mode") == AccessMode.SINGLE_USER
        assert resolution.is_set("access_mode.mode")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "access_mode.mode" in cli_params

    def test_parameter_resolution_tracks_cli_source(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that parameter resolution correctly tracks CLI source."""
        empty_args.single_user_mode = True
        empty_args.multi_user_mode = False

        applicator.apply(empty_args, overrides, resolution)

        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "access_mode.mode" in cli_params
        param_info = cli_params["access_mode.mode"]
        assert param_info.source == ParameterSource.CLI
        assert param_info.origin == "--single-user-mode"
        assert param_info.value == AccessMode.SINGLE_USER

    def test_parameter_resolution_tracks_default_source(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that parameter resolution correctly tracks DEFAULT source when no flag."""
        empty_args.single_user_mode = False
        empty_args.multi_user_mode = False

        applicator.apply(empty_args, overrides, resolution)

        default_params = resolution.latest_by_source(ParameterSource.DEFAULT)
        assert "access_mode.mode" in default_params
        param_info = default_params["access_mode.mode"]
        assert param_info.source == ParameterSource.DEFAULT
        assert param_info.origin == "default"
        assert param_info.value == AccessMode.SINGLE_USER

    def test_only_modifies_access_mode_domain(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that applicator only modifies access_mode configuration."""
        empty_args.single_user_mode = True
        empty_args.multi_user_mode = False

        applicator.apply(empty_args, overrides, resolution)

        # Should only have access_mode key
        assert set(overrides.keys()) == {"access_mode"}
        assert isinstance(overrides["access_mode"], dict)
        assert set(overrides["access_mode"].keys()) == {"mode"}
