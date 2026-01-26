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
            replacement_rules=None,
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

    def test_apply_replacement_rules(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that replacement_rules argument is applied correctly."""
        from src.core.domain.configuration.replacement_rule import ReplacementRule

        empty_args.replacement_rules = [
            "*=qwen-oauth:qwen3-coder-plus",
            "gpt-4=openai:gpt-3.5-turbo",
        ]
        applicator.apply(empty_args, overrides, resolution)

        assert "replacement" in overrides
        rules = overrides["replacement"].get("replacement_rules")
        assert rules is not None
        assert len(rules) == 2
        assert isinstance(rules[0], ReplacementRule)
        assert rules[0].from_pattern == "*"
        assert rules[0].to_backend == "qwen-oauth"
        assert rules[0].to_model == "qwen3-coder-plus"
        assert rules[1].from_pattern == "gpt-4"
        assert rules[1].to_backend == "openai"
        assert rules[1].to_model == "gpt-3.5-turbo"
        assert resolution.is_set("replacement.replacement_rules")
        import json

        env_rules = json.loads(os.environ.get("REPLACEMENT_RULES", "[]"))
        assert len(env_rules) == 2

    def test_apply_multiple_replacement_rules_with_gemini(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test multiple replacement rules including the gemini example."""

        empty_args.replacement_rules = [
            "gemini-3-flash-preview=gemini-oauth-plan:gemini-3-pro-preview",
            "gpt-4=openai:gpt-3.5-turbo",
            "claude-3-opus=anthropic:claude-3-sonnet",
        ]
        applicator.apply(empty_args, overrides, resolution)

        assert "replacement" in overrides
        rules = overrides["replacement"].get("replacement_rules")
        assert rules is not None
        assert len(rules) == 3
        
        # Check gemini rule
        assert rules[0].from_pattern == "gemini-3-flash-preview"
        assert rules[0].to_backend == "gemini-oauth-plan"
        assert rules[0].to_model == "gemini-3-pro-preview"
        
        # Check gpt-4 rule
        assert rules[1].from_pattern == "gpt-4"
        assert rules[1].to_backend == "openai"
        assert rules[1].to_model == "gpt-3.5-turbo"
        
        # Check claude rule (replaced wildcard with specific rule)
        assert rules[2].from_pattern == "claude-3-opus"
        assert rules[2].to_backend == "anthropic"
        assert rules[2].to_model == "claude-3-sonnet"

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
