"""Unit tests for SessionApplicator.

Test-Driven Development: Write tests first (RED), then implement (GREEN).

Requirements:
- 6.1: ConfigurationApplicator delegates to domain-specific applicators
- 6.2: Each domain applicator only modifies its relevant configuration section
- 9.1: Unit tests for each domain applicator
"""

from __future__ import annotations

import argparse
import os
from unittest import mock

import pytest
from src.core.cli_support.protocols import CliArgs, CliOverrides
from src.core.config.parameter_resolution import ParameterResolution


class TestSessionApplicator:
    """Unit tests for SessionApplicator class."""

    @pytest.fixture
    def applicator(self):
        """Create a SessionApplicator instance."""
        from src.core.cli_support.applicators.session_applicator import (
            SessionApplicator,
        )

        return SessionApplicator()

    @pytest.fixture
    def empty_args(self) -> CliArgs:
        """Create empty CLI arguments namespace."""
        return argparse.Namespace(
            disable_interactive_mode=None,
            force_set_project=None,
            project_dir_resolution_model=None,
            project_dir_resolution_mode=None,
            disable_interactive_commands=None,
            quality_verifier_model=None,
            quality_verifier_frequency=None,
            enable_planning_phase=None,
            planning_phase_strong_model=None,
            planning_phase_max_turns=None,
            planning_phase_max_file_writes=None,
            planning_phase_temperature=None,
            planning_phase_top_p=None,
            planning_phase_reasoning_effort=None,
            planning_phase_thinking_budget=None,
            pytest_compression_enabled=None,
            pytest_full_suite_steering_enabled=None,
            pytest_context_saving_enabled=None,
            test_execution_reminder_enabled=None,
            fix_think_tags_enabled=None,
            disable_dangerous_git_commands_protection=None,
            disable_double_ampersand_fixes_for_windows=None,
            droid_path_fix_enabled=None,
            tool_access_allowed_tools=None,
            tool_access_blocked_tools=None,
            tool_access_default_policy=None,
            strict_command_detection=None,
            disable_accounting=None,
        )

    @pytest.fixture
    def overrides(self) -> CliOverrides:
        """Create empty overrides dictionary."""
        return {}

    @pytest.fixture
    def resolution(self) -> ParameterResolution:
        """Create parameter resolution tracker."""
        return ParameterResolution()

    def test_apply_disable_interactive_mode(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that disable_interactive_mode is applied correctly."""
        empty_args.disable_interactive_mode = True
        with mock.patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

            assert "session" in overrides
            assert overrides["session"].get("default_interactive_mode") is False
            assert os.environ.get("DISABLE_INTERACTIVE_MODE") == "True"

    def test_apply_force_set_project(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that force_set_project is applied correctly."""
        empty_args.force_set_project = True
        with mock.patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

            assert "session" in overrides
            assert overrides["session"].get("force_set_project") is True
            assert os.environ.get("FORCE_SET_PROJECT") == "true"

    def test_apply_planning_phase_enabled(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that enable_planning_phase is applied correctly."""
        empty_args.enable_planning_phase = True
        applicator.apply(empty_args, overrides, resolution)

        assert "session" in overrides
        assert "planning_phase" in overrides["session"]
        assert overrides["session"]["planning_phase"].get("enabled") is True

    def test_apply_pytest_compression_enabled(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that pytest_compression_enabled is applied correctly."""
        empty_args.pytest_compression_enabled = True
        applicator.apply(empty_args, overrides, resolution)

        assert "session" in overrides
        assert overrides["session"].get("pytest_compression_enabled") is True

    def test_apply_tool_access_overrides(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that tool access overrides are applied correctly."""
        empty_args.tool_access_allowed_tools = "read_file,write_file"
        empty_args.tool_access_blocked_tools = "delete_file"
        applicator.apply(empty_args, overrides, resolution)

        assert "session" in overrides
        assert "tool_access_global_overrides" in overrides["session"]
        tool_overrides = overrides["session"]["tool_access_global_overrides"]
        assert tool_overrides.get("allowed_patterns") == ["read_file", "write_file"]
        assert tool_overrides.get("blocked_patterns") == ["delete_file"]

    def test_no_modifications_when_all_none(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that no modifications are made when all arguments are None."""
        applicator.apply(empty_args, overrides, resolution)

        # No session overrides should be added
        assert "session" not in overrides

    def test_only_modifies_session_domain(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that applicator only modifies session-related keys (Property 3: Domain Applicator Isolation)."""
        empty_args.disable_interactive_mode = True
        empty_args.pytest_compression_enabled = True

        applicator.apply(empty_args, overrides, resolution)

        # Only session and strict_command_detection should be modified at top level
        allowed_keys = {"session", "strict_command_detection"}
        for key in overrides:
            assert (
                key in allowed_keys
            ), f"SessionApplicator modified unexpected key: {key}"
