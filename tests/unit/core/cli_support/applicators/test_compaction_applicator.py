"""Unit tests for CompactionApplicator.

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


class TestCompactionApplicator:
    """Unit tests for CompactionApplicator class."""

    @pytest.fixture
    def applicator(self):
        """Create a CompactionApplicator instance."""
        from src.core.cli_support.applicators.compaction_applicator import (
            CompactionApplicator,
        )

        return CompactionApplicator()

    @pytest.fixture
    def empty_args(self) -> CliArgs:
        """Create empty CLI arguments namespace."""
        return argparse.Namespace(
            enable_context_compaction=None,
            compaction_min_tokens=None,
        )

    @pytest.fixture
    def overrides(self) -> CliOverrides:
        """Create empty overrides dictionary."""
        return {}

    @pytest.fixture
    def resolution(self) -> ParameterResolution:
        """Create parameter resolution tracker."""
        return ParameterResolution()

    def test_apply_enable_context_compaction(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that enable_context_compaction argument is applied correctly."""
        empty_args.enable_context_compaction = True
        applicator.apply(empty_args, overrides, resolution)

        assert "compaction" in overrides
        assert overrides["compaction"].get("enabled") is True
        assert resolution.is_set("compaction.enabled")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "compaction.enabled" in cli_params

    def test_apply_compaction_min_tokens(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that compaction_min_tokens argument is applied correctly."""
        empty_args.compaction_min_tokens = 100000
        applicator.apply(empty_args, overrides, resolution)

        assert "compaction" in overrides
        assert overrides["compaction"].get("token_threshold") == 100000
        assert resolution.is_set("compaction.token_threshold")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "compaction.token_threshold" in cli_params

    def test_all_compaction_arguments(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that all compaction arguments can be applied together."""
        empty_args.enable_context_compaction = True
        empty_args.compaction_min_tokens = 80000

        applicator.apply(empty_args, overrides, resolution)

        assert "compaction" in overrides
        assert overrides["compaction"].get("enabled") is True
        assert overrides["compaction"].get("token_threshold") == 80000

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

    def test_only_modifies_compaction_domain(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that applicator only modifies compaction keys (Property 3: Domain Applicator Isolation)."""
        empty_args.enable_context_compaction = True
        empty_args.compaction_min_tokens = 50000

        applicator.apply(empty_args, overrides, resolution)

        assert "compaction" in overrides
        assert len(overrides) == 1
        for key in overrides:
            assert (
                key == "compaction"
            ), f"CompactionApplicator modified unexpected key: {key}"
