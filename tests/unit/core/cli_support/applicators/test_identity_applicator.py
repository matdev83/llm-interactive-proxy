"""Unit tests for IdentityApplicator.

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


class TestIdentityApplicator:
    """Unit tests for IdentityApplicator class."""

    @pytest.fixture
    def applicator(self):
        """Create an IdentityApplicator instance."""
        from src.core.cli_support.applicators.identity_applicator import (
            IdentityApplicator,
        )

        return IdentityApplicator()

    @pytest.fixture
    def empty_args(self) -> CliArgs:
        """Create empty CLI arguments namespace."""
        return argparse.Namespace(
            identity_user_agent=None,
            identity_url=None,
            identity_title=None,
        )

    @pytest.fixture
    def overrides(self) -> CliOverrides:
        """Create empty overrides dictionary."""
        return {}

    @pytest.fixture
    def resolution(self) -> ParameterResolution:
        """Create parameter resolution tracker."""
        return ParameterResolution()

    def test_apply_identity_user_agent(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that identity_user_agent argument is applied correctly with mode='override'."""
        empty_args.identity_user_agent = "CustomAgent/1.0"
        applicator.apply(empty_args, overrides, resolution)

        assert "identity" in overrides
        assert "user_agent" in overrides["identity"]
        assert overrides["identity"]["user_agent"].get("mode") == "override"
        assert (
            overrides["identity"]["user_agent"].get("override_value")
            == "CustomAgent/1.0"
        )
        assert resolution.is_set("identity.user_agent.override_value")
        assert resolution.is_set("identity.user_agent.mode")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "identity.user_agent.override_value" in cli_params
        assert "identity.user_agent.mode" in cli_params

    def test_apply_identity_url(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that identity_url argument is applied correctly with mode='override'."""
        empty_args.identity_url = "https://custom.example.com"
        applicator.apply(empty_args, overrides, resolution)

        assert "identity" in overrides
        assert "url" in overrides["identity"]
        assert overrides["identity"]["url"].get("mode") == "override"
        assert (
            overrides["identity"]["url"].get("override_value")
            == "https://custom.example.com"
        )
        assert resolution.is_set("identity.url.override_value")
        assert resolution.is_set("identity.url.mode")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "identity.url.override_value" in cli_params
        assert "identity.url.mode" in cli_params

    def test_apply_identity_title(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that identity_title argument is applied correctly with mode='override'."""
        empty_args.identity_title = "Custom LLM Proxy"
        applicator.apply(empty_args, overrides, resolution)

        assert "identity" in overrides
        assert "title" in overrides["identity"]
        assert overrides["identity"]["title"].get("mode") == "override"
        assert (
            overrides["identity"]["title"].get("override_value") == "Custom LLM Proxy"
        )
        assert resolution.is_set("identity.title.override_value")
        assert resolution.is_set("identity.title.mode")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "identity.title.override_value" in cli_params
        assert "identity.title.mode" in cli_params

    def test_multiple_identity_overrides(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that multiple identity arguments can be applied together."""
        empty_args.identity_user_agent = "MyAgent/2.0"
        empty_args.identity_url = "https://myproxy.example.com"
        empty_args.identity_title = "My Proxy"

        applicator.apply(empty_args, overrides, resolution)

        assert "identity" in overrides
        assert overrides["identity"]["user_agent"]["mode"] == "override"
        assert overrides["identity"]["url"]["mode"] == "override"
        assert overrides["identity"]["title"]["mode"] == "override"

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

    def test_only_modifies_identity_domain(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that applicator only modifies identity keys (Property 3: Domain Applicator Isolation)."""
        empty_args.identity_user_agent = "Agent/1.0"
        empty_args.identity_url = "https://example.com"
        empty_args.identity_title = "Title"

        applicator.apply(empty_args, overrides, resolution)

        assert "identity" in overrides
        assert len(overrides) == 1
        for key in overrides:
            assert (
                key == "identity"
            ), f"IdentityApplicator modified unexpected key: {key}"
