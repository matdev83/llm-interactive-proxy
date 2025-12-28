"""Unit tests for EditPrecisionApplicator.

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


class TestEditPrecisionApplicator:
    """Unit tests for EditPrecisionApplicator class."""

    @pytest.fixture
    def applicator(self):
        """Create an EditPrecisionApplicator instance."""
        from src.core.cli_support.applicators.editprecision_applicator import (
            EditPrecisionApplicator,
        )

        return EditPrecisionApplicator()

    @pytest.fixture
    def empty_args(self) -> CliArgs:
        """Create empty CLI arguments namespace."""
        return argparse.Namespace(
            edit_precision_enabled=None,
            edit_precision_temperature=None,
            edit_precision_min_top_p=None,
            edit_precision_override_top_p=None,
            edit_precision_override_top_k=None,
            edit_precision_target_top_k=None,
            edit_precision_exclude_agents_regex=None,
        )

    @pytest.fixture
    def overrides(self) -> CliOverrides:
        """Create empty overrides dictionary."""
        return {}

    @pytest.fixture
    def resolution(self) -> ParameterResolution:
        """Create parameter resolution tracker."""
        return ParameterResolution()

    def test_apply_edit_precision_enabled(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that edit_precision_enabled argument is applied correctly."""
        empty_args.edit_precision_enabled = True
        applicator.apply(empty_args, overrides, resolution)

        assert "edit_precision" in overrides
        assert overrides["edit_precision"].get("enabled") is True
        assert resolution.is_set("edit_precision.enabled")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "edit_precision.enabled" in cli_params

    def test_apply_edit_precision_temperature(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that edit_precision_temperature argument is applied correctly."""
        empty_args.edit_precision_temperature = 0.1
        applicator.apply(empty_args, overrides, resolution)

        assert "edit_precision" in overrides
        assert overrides["edit_precision"].get("temperature") == 0.1
        assert resolution.is_set("edit_precision.temperature")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "edit_precision.temperature" in cli_params

    def test_edit_precision_temperature_clamped_to_zero(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that edit_precision_temperature is clamped to minimum of 0.0."""
        empty_args.edit_precision_temperature = -0.5
        applicator.apply(empty_args, overrides, resolution)

        assert "edit_precision" in overrides
        assert overrides["edit_precision"].get("temperature") == 0.0

    def test_apply_edit_precision_min_top_p(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that edit_precision_min_top_p argument is applied correctly."""
        empty_args.edit_precision_min_top_p = 0.3
        applicator.apply(empty_args, overrides, resolution)

        assert "edit_precision" in overrides
        assert overrides["edit_precision"].get("min_top_p") == 0.3
        assert resolution.is_set("edit_precision.min_top_p")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "edit_precision.min_top_p" in cli_params

    def test_edit_precision_min_top_p_clamped_to_zero(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that edit_precision_min_top_p is clamped to minimum of 0.0."""
        empty_args.edit_precision_min_top_p = -0.1
        applicator.apply(empty_args, overrides, resolution)

        assert "edit_precision" in overrides
        assert overrides["edit_precision"].get("min_top_p") == 0.0

    def test_apply_edit_precision_override_top_p(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that edit_precision_override_top_p argument is applied correctly."""
        empty_args.edit_precision_override_top_p = False
        applicator.apply(empty_args, overrides, resolution)

        assert "edit_precision" in overrides
        assert overrides["edit_precision"].get("override_top_p") is False
        assert resolution.is_set("edit_precision.override_top_p")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "edit_precision.override_top_p" in cli_params

    def test_apply_edit_precision_override_top_k(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that edit_precision_override_top_k argument is applied correctly."""
        empty_args.edit_precision_override_top_k = False
        applicator.apply(empty_args, overrides, resolution)

        assert "edit_precision" in overrides
        assert overrides["edit_precision"].get("override_top_k") is False
        assert resolution.is_set("edit_precision.override_top_k")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "edit_precision.override_top_k" in cli_params

    def test_apply_edit_precision_target_top_k_positive(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that edit_precision_target_top_k argument is applied correctly when positive."""
        empty_args.edit_precision_target_top_k = 100
        applicator.apply(empty_args, overrides, resolution)

        assert "edit_precision" in overrides
        assert overrides["edit_precision"].get("target_top_k") == 100
        assert resolution.is_set("edit_precision.target_top_k")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "edit_precision.target_top_k" in cli_params

    def test_apply_edit_precision_target_top_k_zero_becomes_none(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that edit_precision_target_top_k becomes None when zero or negative."""
        empty_args.edit_precision_target_top_k = 0
        applicator.apply(empty_args, overrides, resolution)

        assert "edit_precision" in overrides
        assert overrides["edit_precision"].get("target_top_k") is None

    def test_apply_edit_precision_exclude_agents_regex(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that edit_precision_exclude_agents_regex argument is applied correctly."""
        empty_args.edit_precision_exclude_agents_regex = "^(cursor|opencode)$"
        applicator.apply(empty_args, overrides, resolution)

        assert "edit_precision" in overrides
        assert overrides["edit_precision"].get("exclude_agents_regex") == "^(cursor|opencode)$"
        assert resolution.is_set("edit_precision.exclude_agents_regex")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "edit_precision.exclude_agents_regex" in cli_params

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

    def test_only_modifies_edit_precision_domain(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that applicator only modifies edit_precision keys (Property 3: Domain Applicator Isolation)."""
        empty_args.edit_precision_enabled = True
        empty_args.edit_precision_temperature = 0.1
        empty_args.edit_precision_min_top_p = 0.3
        empty_args.edit_precision_override_top_p = False
        empty_args.edit_precision_exclude_agents_regex = "test.*"

        applicator.apply(empty_args, overrides, resolution)

        assert "edit_precision" in overrides
        assert len(overrides) == 1
        for key in overrides:
            assert (
                key == "edit_precision"
            ), f"EditPrecisionApplicator modified unexpected key: {key}"
