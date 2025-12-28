"""Unit tests for FailureHandlingApplicator.

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


class TestFailureHandlingApplicator:
    """Unit tests for FailureHandlingApplicator class."""

    @pytest.fixture
    def applicator(self):
        """Create a FailureHandlingApplicator instance."""
        from src.core.cli_support.applicators.failurehandling_applicator import (
            FailureHandlingApplicator,
        )

        return FailureHandlingApplicator()

    @pytest.fixture
    def empty_args(self) -> CliArgs:
        """Create empty CLI arguments namespace."""
        return argparse.Namespace(
            disable_failure_handling=False,
            max_silent_wait=None,
            total_timeout_budget=None,
            keepalive_interval=None,
            max_failover_hops=None,
            min_retry_wait=None,
        )

    @pytest.fixture
    def overrides(self) -> CliOverrides:
        """Create empty overrides dictionary."""
        return {}

    @pytest.fixture
    def resolution(self) -> ParameterResolution:
        """Create parameter resolution tracker."""
        return ParameterResolution()

    def test_apply_disable_failure_handling(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that disable_failure_handling argument is applied correctly and sets environment variable."""
        empty_args.disable_failure_handling = True
        with mock.patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

            assert "failure_handling" in overrides
            assert overrides["failure_handling"].get("enabled") is False
            assert os.environ.get("DISABLE_FAILURE_HANDLING") == "1"
            assert resolution.is_set("failure_handling.enabled")
            cli_params = resolution.latest_by_source(ParameterSource.CLI)
            assert "failure_handling.enabled" in cli_params

    def test_apply_max_silent_wait(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that max_silent_wait argument is applied correctly and sets environment variable."""
        empty_args.max_silent_wait = 60
        with mock.patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

            assert "failure_handling" in overrides
            assert overrides["failure_handling"].get("max_silent_wait") == 60
            assert os.environ.get("FAILURE_HANDLING_MAX_SILENT_WAIT") == "60"
            assert resolution.is_set("failure_handling.max_silent_wait")
            cli_params = resolution.latest_by_source(ParameterSource.CLI)
            assert "failure_handling.max_silent_wait" in cli_params

    def test_apply_total_timeout_budget(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that total_timeout_budget argument is applied correctly and sets environment variable."""
        empty_args.total_timeout_budget = 300
        with mock.patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

            assert "failure_handling" in overrides
            assert overrides["failure_handling"].get("total_timeout_budget") == 300
            assert os.environ.get("FAILURE_HANDLING_TOTAL_TIMEOUT_BUDGET") == "300"
            assert resolution.is_set("failure_handling.total_timeout_budget")
            cli_params = resolution.latest_by_source(ParameterSource.CLI)
            assert "failure_handling.total_timeout_budget" in cli_params

    def test_apply_keepalive_interval(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that keepalive_interval argument is applied correctly and sets environment variable."""
        empty_args.keepalive_interval = 10
        with mock.patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

            assert "failure_handling" in overrides
            assert overrides["failure_handling"].get("keepalive_interval") == 10
            assert os.environ.get("FAILURE_HANDLING_KEEPALIVE_INTERVAL") == "10"
            assert resolution.is_set("failure_handling.keepalive_interval")
            cli_params = resolution.latest_by_source(ParameterSource.CLI)
            assert "failure_handling.keepalive_interval" in cli_params

    def test_apply_max_failover_hops(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that max_failover_hops argument is applied correctly and sets environment variable."""
        empty_args.max_failover_hops = 3
        with mock.patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

            assert "failure_handling" in overrides
            assert overrides["failure_handling"].get("max_failover_hops") == 3
            assert os.environ.get("FAILURE_HANDLING_MAX_FAILOVER_HOPS") == "3"
            assert resolution.is_set("failure_handling.max_failover_hops")
            cli_params = resolution.latest_by_source(ParameterSource.CLI)
            assert "failure_handling.max_failover_hops" in cli_params

    def test_apply_min_retry_wait(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that min_retry_wait argument is applied correctly and sets environment variable."""
        empty_args.min_retry_wait = 5
        with mock.patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

            assert "failure_handling" in overrides
            assert overrides["failure_handling"].get("min_retry_wait") == 5
            assert os.environ.get("FAILURE_HANDLING_MIN_RETRY_WAIT") == "5"
            assert resolution.is_set("failure_handling.min_retry_wait")
            cli_params = resolution.latest_by_source(ParameterSource.CLI)
            assert "failure_handling.min_retry_wait" in cli_params

    def test_no_modifications_when_all_none(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that no modifications are made when all arguments are None or defaults."""
        with mock.patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

            assert len(overrides) == 0
            assert len(resolution.latest_by_source(ParameterSource.CLI)) == 0

    def test_only_modifies_failure_handling_domain(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that applicator only modifies failure_handling keys (Property 3: Domain Applicator Isolation)."""
        empty_args.max_silent_wait = 30
        empty_args.total_timeout_budget = 120
        empty_args.keepalive_interval = 5
        empty_args.max_failover_hops = 2
        empty_args.min_retry_wait = 3

        with mock.patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

            assert "failure_handling" in overrides
            assert len(overrides) == 1
            for key in overrides:
                assert (
                    key == "failure_handling"
                ), f"FailureHandlingApplicator modified unexpected key: {key}"
