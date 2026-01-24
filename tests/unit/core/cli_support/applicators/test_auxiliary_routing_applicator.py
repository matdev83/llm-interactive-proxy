"""Tests for AuxiliaryRoutingApplicator."""

import argparse

import pytest
from src.core.cli_support.applicators.auxiliary_routing_applicator import (
    AuxiliaryRoutingApplicator,
)
from src.core.cli_support.protocols import CliArgs, CliOverrides
from src.core.config.parameter_resolution import ParameterResolution, ParameterSource


class TestAuxiliaryRoutingApplicator:
    """Tests for AuxiliaryRoutingApplicator."""

    @pytest.fixture
    def applicator(self):
        """Create an AuxiliaryRoutingApplicator instance."""
        return AuxiliaryRoutingApplicator()

    @pytest.fixture
    def empty_args(self) -> CliArgs:
        """Create empty CLI arguments namespace."""
        return argparse.Namespace(
            auxiliary_routing_enabled=None,
            auxiliary_routing_backend=None,
            auxiliary_routing_model=None,
            auxiliary_routing_max_messages=None,
        )

    @pytest.fixture
    def overrides(self) -> CliOverrides:
        """Create empty overrides dictionary."""
        return {}

    @pytest.fixture
    def resolution(self) -> ParameterResolution:
        """Create parameter resolution tracker."""
        return ParameterResolution()

    def test_applies_enabled_flag(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that --enable-auxiliary-routing is applied."""
        empty_args.auxiliary_routing_enabled = True
        applicator.apply(empty_args, overrides, resolution)

        assert "auxiliary_routing" in overrides
        assert overrides["auxiliary_routing"]["enabled"] is True
        assert resolution.is_set("auxiliary_routing.enabled")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "auxiliary_routing.enabled" in cli_params

    def test_applies_backend(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that --auxiliary-routing-backend is applied."""
        empty_args.auxiliary_routing_backend = "openrouter"
        applicator.apply(empty_args, overrides, resolution)

        assert "auxiliary_routing" in overrides
        assert overrides["auxiliary_routing"]["backend"] == "openrouter"
        assert resolution.is_set("auxiliary_routing.backend")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "auxiliary_routing.backend" in cli_params

    def test_applies_model(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that --auxiliary-routing-model is applied."""
        empty_args.auxiliary_routing_model = "google/gemini-flash-1.5"
        applicator.apply(empty_args, overrides, resolution)

        assert "auxiliary_routing" in overrides
        assert overrides["auxiliary_routing"]["model"] == "google/gemini-flash-1.5"
        assert resolution.is_set("auxiliary_routing.model")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "auxiliary_routing.model" in cli_params

    def test_applies_max_messages(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that --auxiliary-routing-max-messages is applied."""
        empty_args.auxiliary_routing_max_messages = 5
        applicator.apply(empty_args, overrides, resolution)

        assert "auxiliary_routing" in overrides
        assert overrides["auxiliary_routing"]["max_message_count"] == 5
        assert resolution.is_set("auxiliary_routing.max_message_count")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "auxiliary_routing.max_message_count" in cli_params

    def test_applies_all_arguments(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that all arguments are applied together."""
        empty_args.auxiliary_routing_enabled = True
        empty_args.auxiliary_routing_backend = "openrouter"
        empty_args.auxiliary_routing_model = "google/gemini-flash-1.5"
        empty_args.auxiliary_routing_max_messages = 5

        applicator.apply(empty_args, overrides, resolution)

        assert "auxiliary_routing" in overrides
        assert overrides["auxiliary_routing"]["enabled"] is True
        assert overrides["auxiliary_routing"]["backend"] == "openrouter"
        assert overrides["auxiliary_routing"]["model"] == "google/gemini-flash-1.5"
        assert overrides["auxiliary_routing"]["max_message_count"] == 5

    def test_no_overrides_when_no_args(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that no overrides are created when no arguments are provided."""
        applicator.apply(empty_args, overrides, resolution)

        assert len(overrides) == 0
        assert len(resolution.latest_by_source(ParameterSource.CLI)) == 0
