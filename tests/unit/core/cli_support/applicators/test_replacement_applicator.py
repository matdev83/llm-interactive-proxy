"""Unit tests for ReplacementApplicator.

Requirements:
- 6.1: ConfigurationApplicator delegates to domain-specific applicators
- 6.2: Each domain applicator only modifies its relevant configuration section
- 9.1: Unit tests for each domain applicator
"""

from __future__ import annotations

import argparse
import os

import pytest
from src.core.cli_support.protocols import CliArgs, CliOverrides
from src.core.config.parameter_resolution import ParameterResolution, ParameterSource


class TestReplacementApplicator:
    """Unit tests for ReplacementApplicator class."""

    @pytest.fixture
    def applicator(self):
        """Create a ReplacementApplicator instance."""
        from src.core.cli_support.applicators.replacement_applicator import (
            ReplacementApplicator,
        )

        return ReplacementApplicator()

    @pytest.fixture
    def empty_args(self) -> CliArgs:
        """Create empty CLI arguments namespace."""
        return argparse.Namespace(
            replacement_enabled=None,
            replacement_probability=None,
            replacement_backend_model=None,
            replacement_turn_count=None,
        )

    @pytest.fixture
    def overrides(self) -> CliOverrides:
        """Create empty overrides dictionary."""
        return {}

    @pytest.fixture
    def resolution(self) -> ParameterResolution:
        """Create parameter resolution tracker."""
        return ParameterResolution()

    def test_apply_replacement_enabled(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that replacement_enabled argument is applied correctly."""
        empty_args.replacement_enabled = True
        applicator.apply(empty_args, overrides, resolution)

        assert "replacement" in overrides
        assert overrides["replacement"].get("enabled") is True
        assert resolution.is_set("replacement.enabled")
        assert os.environ.get("REPLACEMENT_ENABLED") == "true"

    def test_apply_replacement_probability(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that replacement_probability argument is applied correctly."""
        empty_args.replacement_probability = 0.5
        applicator.apply(empty_args, overrides, resolution)

        assert "replacement" in overrides
        assert overrides["replacement"].get("probability") == 0.5
        assert resolution.is_set("replacement.probability")
        assert os.environ.get("REPLACEMENT_PROBABILITY") == "0.5"

    def test_apply_replacement_backend_model(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that replacement_backend_model argument is applied correctly."""
        empty_args.replacement_backend_model = "openai:gpt-4"
        applicator.apply(empty_args, overrides, resolution)

        assert "replacement" in overrides
        assert overrides["replacement"].get("backend_model") == "openai:gpt-4"
        assert resolution.is_set("replacement.backend_model")
        assert os.environ.get("REPLACEMENT_BACKEND_MODEL") == "openai:gpt-4"

    def test_apply_replacement_turn_count(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that replacement_turn_count argument is applied correctly."""
        empty_args.replacement_turn_count = 3
        applicator.apply(empty_args, overrides, resolution)

        assert "replacement" in overrides
        assert overrides["replacement"].get("turn_count") == 3
        assert resolution.is_set("replacement.turn_count")
        assert os.environ.get("REPLACEMENT_TURN_COUNT") == "3"

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

    def test_only_modifies_replacement_domain(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that applicator only modifies replacement domain."""
        empty_args.replacement_enabled = True
        empty_args.replacement_probability = 0.3

        applicator.apply(empty_args, overrides, resolution)

        assert "replacement" in overrides
        assert len(overrides) == 1
