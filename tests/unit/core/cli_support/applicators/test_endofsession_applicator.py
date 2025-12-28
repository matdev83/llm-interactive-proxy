"""Unit tests for EndOfSessionApplicator.

Test-Driven Development: Write tests first (RED), then implement (GREEN).

Requirements:
- 6.1: ConfigurationApplicator delegates to domain-specific applicators
- 6.2: Each domain applicator only modifies its relevant configuration section
- 9.1: Unit tests for each domain applicator
"""

from __future__ import annotations

import argparse

import pytest
from src.core.cli_support.protocols import CliArgs, CliOverrides
from src.core.config.parameter_resolution import ParameterResolution, ParameterSource


class TestEndOfSessionApplicator:
    """Unit tests for EndOfSessionApplicator class."""

    @pytest.fixture
    def applicator(self):
        """Create an EndOfSessionApplicator instance."""
        from src.core.cli_support.applicators.endofsession_applicator import (
            EndOfSessionApplicator,
        )

        return EndOfSessionApplicator()

    @pytest.fixture
    def empty_args(self) -> CliArgs:
        """Create empty CLI arguments namespace."""
        return argparse.Namespace(
            end_of_session_enabled=None,
            end_of_session_emit_events=None,
            end_of_session_dispatch_timeout_seconds=None,
        )

    @pytest.fixture
    def overrides(self) -> CliOverrides:
        """Create empty overrides dictionary."""
        return {}

    @pytest.fixture
    def resolution(self) -> ParameterResolution:
        """Create parameter resolution tracker."""
        return ParameterResolution()

    def test_apply_end_of_session_enabled(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that end_of_session_enabled argument is applied correctly."""
        empty_args.end_of_session_enabled = True
        applicator.apply(empty_args, overrides, resolution)

        assert "end_of_session" in overrides
        assert overrides["end_of_session"].get("enabled") is True
        assert resolution.is_set("end_of_session.enabled")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "end_of_session.enabled" in cli_params

    def test_apply_end_of_session_emit_events(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that end_of_session_emit_events argument is applied correctly."""
        empty_args.end_of_session_emit_events = True
        applicator.apply(empty_args, overrides, resolution)

        assert "end_of_session" in overrides
        assert overrides["end_of_session"].get("emit_events") is True
        assert resolution.is_set("end_of_session.emit_events")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "end_of_session.emit_events" in cli_params

    def test_apply_end_of_session_dispatch_timeout(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that end_of_session_dispatch_timeout_seconds argument is applied correctly."""
        empty_args.end_of_session_dispatch_timeout_seconds = 30
        applicator.apply(empty_args, overrides, resolution)

        assert "end_of_session" in overrides
        assert overrides["end_of_session"].get("dispatch_timeout_seconds") == 30
        assert resolution.is_set("end_of_session.dispatch_timeout_seconds")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "end_of_session.dispatch_timeout_seconds" in cli_params

    def test_all_end_of_session_arguments(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that all end_of_session arguments can be applied together."""
        empty_args.end_of_session_enabled = True
        empty_args.end_of_session_emit_events = False
        empty_args.end_of_session_dispatch_timeout_seconds = 60

        applicator.apply(empty_args, overrides, resolution)

        assert "end_of_session" in overrides
        assert overrides["end_of_session"].get("enabled") is True
        assert overrides["end_of_session"].get("emit_events") is False
        assert overrides["end_of_session"].get("dispatch_timeout_seconds") == 60

    def test_no_modifications_when_all_none(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that no modifications are made when all arguments are None."""
        applicator.apply(empty_args, overrides, resolution)

        assert len(overrides) == 0
        assert len(resolution.latest_by_source(ParameterSource.CLI)) == 0

    def test_only_modifies_end_of_session_domain(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that applicator only modifies end_of_session keys (Property 3: Domain Applicator Isolation)."""
        empty_args.end_of_session_enabled = True
        empty_args.end_of_session_emit_events = True
        empty_args.end_of_session_dispatch_timeout_seconds = 45

        applicator.apply(empty_args, overrides, resolution)

        assert "end_of_session" in overrides
        assert len(overrides) == 1
        for key in overrides:
            assert (
                key == "end_of_session"
            ), f"EndOfSessionApplicator modified unexpected key: {key}"
