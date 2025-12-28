"""Unit tests for SandboxingApplicator.

Test-Driven Development: Write tests first (RED), then implement (GREEN).

Requirements:
- 6.1: ConfigurationApplicator delegates to domain-specific applicators
- 6.2: Each domain applicator only modifies its relevant configuration section
- 6.3: Environment variables are handled within applicator's scope
- 9.1: Unit tests for each domain applicator
"""

from __future__ import annotations

import argparse
import os
from unittest import mock

import pytest
from src.core.cli_support.protocols import CliArgs, CliOverrides
from src.core.config.parameter_resolution import ParameterResolution, ParameterSource


class TestSandboxingApplicator:
    """Unit tests for SandboxingApplicator class."""

    @pytest.fixture
    def applicator(self):
        """Create a SandboxingApplicator instance."""
        from src.core.cli_support.applicators.sandboxing_applicator import (
            SandboxingApplicator,
        )

        return SandboxingApplicator()

    @pytest.fixture
    def empty_args(self) -> CliArgs:
        """Create empty CLI arguments namespace."""
        return argparse.Namespace(enable_sandboxing=None)

    @pytest.fixture
    def overrides(self) -> CliOverrides:
        """Create empty overrides dictionary."""
        return {}

    @pytest.fixture
    def resolution(self) -> ParameterResolution:
        """Create parameter resolution tracker."""
        return ParameterResolution()

    def test_apply_enable_sandboxing_true(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that enable_sandboxing=True is applied correctly and sets environment variable."""
        empty_args.enable_sandboxing = True
        with mock.patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

            assert "sandboxing" in overrides
            assert overrides["sandboxing"].get("enabled") is True
            assert os.environ.get("ENABLE_SANDBOXING") == "true"
            assert resolution.is_set("sandboxing.enabled")
            cli_params = resolution.latest_by_source(ParameterSource.CLI)
            assert "sandboxing.enabled" in cli_params

    def test_apply_enable_sandboxing_false(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that enable_sandboxing=False is applied correctly and sets environment variable."""
        empty_args.enable_sandboxing = False
        with mock.patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

            assert "sandboxing" in overrides
            assert overrides["sandboxing"].get("enabled") is False
            assert os.environ.get("ENABLE_SANDBOXING") == "false"
            assert resolution.is_set("sandboxing.enabled")
            cli_params = resolution.latest_by_source(ParameterSource.CLI)
            assert "sandboxing.enabled" in cli_params

    def test_no_modifications_when_none(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that no modifications are made when argument is None."""
        with mock.patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

            assert len(overrides) == 0
            assert len(resolution.latest_by_source(ParameterSource.CLI)) == 0
            assert os.environ.get("ENABLE_SANDBOXING") is None

    def test_only_modifies_sandboxing_domain(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that applicator only modifies sandboxing keys (Property 3: Domain Applicator Isolation)."""
        empty_args.enable_sandboxing = True

        with mock.patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

            assert "sandboxing" in overrides
            assert len(overrides) == 1
            for key in overrides:
                assert (
                    key == "sandboxing"
                ), f"SandboxingApplicator modified unexpected key: {key}"
