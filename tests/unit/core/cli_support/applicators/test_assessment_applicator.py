"""Unit tests for AssessmentApplicator.

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


class TestAssessmentApplicator:
    """Unit tests for AssessmentApplicator class."""

    @pytest.fixture
    def applicator(self):
        """Create an AssessmentApplicator instance."""
        from src.core.cli_support.applicators.assessment_applicator import (
            AssessmentApplicator,
        )

        return AssessmentApplicator()

    @pytest.fixture
    def empty_args(self) -> CliArgs:
        """Create empty CLI arguments namespace."""
        return argparse.Namespace(
            llm_assessment_enabled=None,
            llm_assessment_turn_threshold=None,
            llm_assessment_confidence_threshold=None,
            llm_assessment_model=None,
            llm_assessment_history_window=None,
        )

    @pytest.fixture
    def overrides(self) -> CliOverrides:
        """Create empty overrides dictionary."""
        return {}

    @pytest.fixture
    def resolution(self) -> ParameterResolution:
        """Create parameter resolution tracker."""
        return ParameterResolution()

    def test_apply_llm_assessment_enabled(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that llm_assessment_enabled argument is applied correctly."""
        empty_args.llm_assessment_enabled = True
        applicator.apply(empty_args, overrides, resolution)

        assert "assessment" in overrides
        assert overrides["assessment"].get("enabled") is True
        assert resolution.is_set("assessment.enabled")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "assessment.enabled" in cli_params

    def test_apply_llm_assessment_turn_threshold(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that llm_assessment_turn_threshold argument is applied correctly."""
        empty_args.llm_assessment_turn_threshold = 5
        applicator.apply(empty_args, overrides, resolution)

        assert "assessment" in overrides
        assert overrides["assessment"].get("turn_threshold") == 5
        assert resolution.is_set("assessment.turn_threshold")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "assessment.turn_threshold" in cli_params

    def test_apply_llm_assessment_confidence_threshold(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that llm_assessment_confidence_threshold argument is applied correctly."""
        empty_args.llm_assessment_confidence_threshold = 0.85
        applicator.apply(empty_args, overrides, resolution)

        assert "assessment" in overrides
        assert overrides["assessment"].get("confidence_threshold") == 0.85
        assert resolution.is_set("assessment.confidence_threshold")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "assessment.confidence_threshold" in cli_params

    def test_apply_llm_assessment_model(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that llm_assessment_model argument is applied correctly with backend:model format."""
        empty_args.llm_assessment_model = "openai:gpt-4"
        applicator.apply(empty_args, overrides, resolution)

        assert "assessment" in overrides
        assert overrides["assessment"].get("backend") == "openai"
        assert overrides["assessment"].get("model") == "gpt-4"
        assert resolution.is_set("assessment.backend")
        assert resolution.is_set("assessment.model")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "assessment.backend" in cli_params
        assert "assessment.model" in cli_params

    def test_apply_llm_assessment_history_window(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that llm_assessment_history_window argument is applied correctly."""
        empty_args.llm_assessment_history_window = 10
        applicator.apply(empty_args, overrides, resolution)

        assert "assessment" in overrides
        assert overrides["assessment"].get("history_window") == 10
        assert resolution.is_set("assessment.history_window")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "assessment.history_window" in cli_params

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

    def test_only_modifies_assessment_domain(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that applicator only modifies assessment keys (Property 3: Domain Applicator Isolation)."""
        empty_args.llm_assessment_enabled = True
        empty_args.llm_assessment_turn_threshold = 3
        empty_args.llm_assessment_confidence_threshold = 0.9
        empty_args.llm_assessment_model = "gemini:gemini-pro"
        empty_args.llm_assessment_history_window = 15

        applicator.apply(empty_args, overrides, resolution)

        assert "assessment" in overrides
        assert len(overrides) == 1
        for key in overrides:
            assert (
                key == "assessment"
            ), f"AssessmentApplicator modified unexpected key: {key}"
