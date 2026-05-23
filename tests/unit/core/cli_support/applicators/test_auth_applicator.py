"""Unit tests for AuthApplicator.

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


class TestAuthApplicator:
    """Unit tests for AuthApplicator class."""

    @pytest.fixture
    def applicator(self):
        """Create an AuthApplicator instance."""
        from src.core.cli_support.applicators.auth_applicator import AuthApplicator

        return AuthApplicator()

    @pytest.fixture
    def empty_args(self) -> CliArgs:
        """Create empty CLI arguments namespace."""
        return argparse.Namespace(
            disable_auth=None,
            disable_sso_captcha=None,
            enable_sso=None,
            sso_config_path=None,
            sso_provider=None,
            sso_auth_mode=None,
            trusted_ips=None,
            disable_redact_api_keys_in_prompts=None,
            brute_force_protection_enabled=None,
            auth_max_failed_attempts=None,
            auth_brute_force_ttl=None,
            auth_initial_block_seconds=None,
            auth_block_multiplier=None,
            auth_max_block_seconds=None,
        )

    @pytest.fixture
    def overrides(self) -> CliOverrides:
        """Create empty overrides dictionary."""
        return {}

    @pytest.fixture
    def resolution(self) -> ParameterResolution:
        """Create parameter resolution tracker."""
        return ParameterResolution()

    def test_apply_disable_auth(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that disable_auth argument is applied correctly."""
        empty_args.disable_auth = True
        applicator.apply(empty_args, overrides, resolution)

        assert "auth" in overrides
        assert overrides["auth"].get("disable_auth") is True
        assert resolution.is_set("auth.disable_auth")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "auth.disable_auth" in cli_params

    def test_apply_disable_sso_captcha(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that disable_sso_captcha is applied correctly."""
        empty_args.disable_sso_captcha = True
        applicator.apply(empty_args, overrides, resolution)

        assert "sso" in overrides
        assert "captcha" in overrides["sso"]
        assert overrides["sso"]["captcha"].get("enabled") is False

    def test_apply_enable_sso(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that enable_sso is applied correctly."""
        empty_args.enable_sso = True
        applicator.apply(empty_args, overrides, resolution)

        assert "sso" in overrides
        assert overrides["sso"].get("enabled") is True
        assert resolution.is_set("sso.enabled")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "sso.enabled" in cli_params

    def test_apply_brute_force_protection_enabled(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that brute_force_protection_enabled is applied correctly."""
        empty_args.brute_force_protection_enabled = True
        applicator.apply(empty_args, overrides, resolution)

        assert "auth" in overrides
        assert "brute_force_protection" in overrides["auth"]
        assert overrides["auth"]["brute_force_protection"].get("enabled") is True

    def test_apply_brute_force_max_failed_attempts(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that auth_max_failed_attempts is applied correctly."""
        empty_args.auth_max_failed_attempts = 5
        applicator.apply(empty_args, overrides, resolution)

        assert "auth" in overrides
        assert "brute_force_protection" in overrides["auth"]
        assert (
            overrides["auth"]["brute_force_protection"].get("max_failed_attempts") == 5
        )

    def test_apply_brute_force_ttl(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that auth_brute_force_ttl is applied correctly."""
        empty_args.auth_brute_force_ttl = 300
        applicator.apply(empty_args, overrides, resolution)

        assert "auth" in overrides
        assert "brute_force_protection" in overrides["auth"]
        assert overrides["auth"]["brute_force_protection"].get("ttl_seconds") == 300

    def test_no_modifications_when_all_none(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that no modifications are made when all arguments are None."""
        applicator.apply(empty_args, overrides, resolution)

        # No auth or sso overrides should be added
        assert "auth" not in overrides
        assert "sso" not in overrides

    def test_only_modifies_auth_and_sso_domain(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that applicator only modifies auth and sso keys (Property 3: Domain Applicator Isolation)."""
        empty_args.disable_auth = True
        empty_args.enable_sso = True
        empty_args.brute_force_protection_enabled = True

        applicator.apply(empty_args, overrides, resolution)

        # Only auth and sso should be modified at top level
        allowed_keys = {"auth", "sso"}
        for key in overrides:
            assert key in allowed_keys, f"AuthApplicator modified unexpected key: {key}"
