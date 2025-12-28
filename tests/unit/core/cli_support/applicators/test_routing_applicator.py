"""Unit tests for RoutingApplicator.

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


class TestRoutingApplicator:
    """Unit tests for RoutingApplicator class."""

    @pytest.fixture
    def applicator(self):
        """Create a RoutingApplicator instance."""
        from src.core.cli_support.applicators.routing_applicator import (
            RoutingApplicator,
        )

        return RoutingApplicator()

    @pytest.fixture
    def empty_args(self) -> CliArgs:
        """Create empty CLI arguments namespace."""
        return argparse.Namespace(
            disable_routing_with_backend_ids=None,
            disable_routing_with_backend_names=None,
            disable_routing_with_only_model_names=None,
        )

    @pytest.fixture
    def overrides(self) -> CliOverrides:
        """Create empty overrides dictionary."""
        return {}

    @pytest.fixture
    def resolution(self) -> ParameterResolution:
        """Create parameter resolution tracker."""
        return ParameterResolution()

    def test_apply_disable_routing_with_backend_ids(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that disable_routing_with_backend_ids argument is applied correctly."""
        empty_args.disable_routing_with_backend_ids = True
        applicator.apply(empty_args, overrides, resolution)

        assert "routing" in overrides
        assert overrides["routing"].get("disable_backend_ids") is True
        assert resolution.is_set("routing.disable_backend_ids")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "routing.disable_backend_ids" in cli_params

    def test_apply_disable_routing_with_backend_names(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that disable_routing_with_backend_names argument is applied correctly."""
        empty_args.disable_routing_with_backend_names = True
        applicator.apply(empty_args, overrides, resolution)

        assert "routing" in overrides
        assert overrides["routing"].get("disable_backend_names") is True
        assert resolution.is_set("routing.disable_backend_names")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "routing.disable_backend_names" in cli_params

    def test_apply_disable_routing_with_only_model_names(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that disable_routing_with_only_model_names argument is applied correctly."""
        empty_args.disable_routing_with_only_model_names = True
        applicator.apply(empty_args, overrides, resolution)

        assert "routing" in overrides
        assert overrides["routing"].get("disable_model_names") is True
        assert resolution.is_set("routing.disable_model_names")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "routing.disable_model_names" in cli_params

    def test_all_routing_disable_flags(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that all routing disable flags can be applied together."""
        empty_args.disable_routing_with_backend_ids = True
        empty_args.disable_routing_with_backend_names = True
        empty_args.disable_routing_with_only_model_names = True

        applicator.apply(empty_args, overrides, resolution)

        assert "routing" in overrides
        assert overrides["routing"]["disable_backend_ids"] is True
        assert overrides["routing"]["disable_backend_names"] is True
        assert overrides["routing"]["disable_model_names"] is True

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

    def test_only_modifies_routing_domain(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that applicator only modifies routing keys (Property 3: Domain Applicator Isolation)."""
        empty_args.disable_routing_with_backend_ids = True
        empty_args.disable_routing_with_backend_names = True
        empty_args.disable_routing_with_only_model_names = True

        applicator.apply(empty_args, overrides, resolution)

        assert "routing" in overrides
        assert len(overrides) == 1
        for key in overrides:
            assert key == "routing", f"RoutingApplicator modified unexpected key: {key}"
