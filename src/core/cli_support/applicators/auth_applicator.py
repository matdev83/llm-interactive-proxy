"""Auth Applicator - Extracts and applies authentication-related CLI arguments.

This applicator handles:
- disable_auth, disable_redact_api_keys_in_prompts
- SSO settings (enable_sso, disable_sso_captcha, sso_config_path, sso_provider, sso_auth_mode)
- Brute force protection settings
- trusted_ips

Requirements satisfied:
- 6.1: ConfigurationApplicator delegates to domain-specific applicators
- 6.2: Each domain applicator only modifies its relevant configuration section
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.cli_support.protocols import CliArgs, CliOverrides
    from src.core.config.parameter_resolution import ParameterResolution

from src.core.config.parameter_resolution import ParameterSource

logger = logging.getLogger(__name__)


class AuthApplicator:
    """Applies authentication-related CLI arguments to configuration.

    Handles:
    - Authentication settings (disable_auth, redact_api_keys)
    - SSO configuration
    - Brute force protection settings
    - Trusted IPs
    """

    def apply(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply authentication-related CLI arguments to configuration overrides.

        Args:
            args: Parsed command-line arguments namespace
            overrides: Dictionary to collect configuration overrides
            resolution: Parameter resolution tracker for recording sources
        """
        self._apply_auth_settings(args, overrides, resolution)
        self._apply_sso_settings(args, overrides, resolution)
        self._apply_brute_force_settings(args, overrides, resolution)

    def _apply_auth_settings(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply authentication settings."""
        if getattr(args, "disable_auth", None) is not None:
            auth_overrides = overrides.setdefault("auth", {})
            auth_overrides["disable_auth"] = args.disable_auth
            resolution.record(
                "auth.disable_auth",
                args.disable_auth,
                ParameterSource.CLI,
                origin="--disable-auth",
            )

        if getattr(args, "disable_redact_api_keys_in_prompts", None) is not None:
            auth_overrides = overrides.setdefault("auth", {})
            auth_overrides["redact_api_keys_in_prompts"] = (
                not args.disable_redact_api_keys_in_prompts
            )
            resolution.record(
                "auth.redact_api_keys_in_prompts",
                not args.disable_redact_api_keys_in_prompts,
                ParameterSource.CLI,
                origin="--disable-redact-api-keys-in-prompts",
            )

        if getattr(args, "trusted_ips", None) is not None:
            auth_overrides = overrides.setdefault("auth", {})
            auth_overrides["trusted_ips"] = args.trusted_ips
            resolution.record(
                "auth.trusted_ips",
                args.trusted_ips,
                ParameterSource.CLI,
                origin="--trusted-ip",
            )

    def _apply_sso_settings(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply SSO settings."""
        if getattr(args, "disable_sso_captcha", None) is not None:
            sso_overrides = overrides.setdefault("sso", {})
            captcha_overrides = sso_overrides.setdefault("captcha", {})
            captcha_overrides["enabled"] = not args.disable_sso_captcha
            resolution.record(
                "sso.captcha.enabled",
                not args.disable_sso_captcha,
                ParameterSource.CLI,
                origin="--disable-sso-captcha",
            )

        if getattr(args, "enable_sso", None) is not None:
            sso_overrides = overrides.setdefault("sso", {})
            sso_overrides["enabled"] = True
            resolution.record(
                "sso.enabled",
                True,
                ParameterSource.CLI,
                origin="--enable-sso",
            )

        if getattr(args, "sso_config_path", None) is not None:
            self._load_sso_config(args.sso_config_path, overrides, resolution)

        if getattr(args, "sso_provider", None) is not None:
            sso_overrides = overrides.setdefault("sso", {})
            providers_overrides = sso_overrides.setdefault("providers", {})
            specified_provider = args.sso_provider
            providers_overrides["_cli_selected_provider"] = specified_provider
            resolution.record(
                "sso.providers",
                f"only {specified_provider} enabled",
                ParameterSource.CLI,
                origin="--sso-provider",
            )
            if specified_provider not in providers_overrides:
                providers_overrides[specified_provider] = {}
            providers_overrides[specified_provider]["enabled"] = True

        if getattr(args, "sso_auth_mode", None) is not None:
            sso_overrides = overrides.setdefault("sso", {})
            auth_overrides = sso_overrides.setdefault("authorization", {})
            auth_overrides["mode"] = args.sso_auth_mode
            resolution.record(
                "sso.authorization.mode",
                args.sso_auth_mode,
                ParameterSource.CLI,
                origin="--sso-auth-mode",
            )

    def _load_sso_config(
        self,
        sso_config_path: str,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Load SSO configuration from file."""
        import yaml

        sso_config_file = Path(sso_config_path)
        if not sso_config_file.exists():
            raise ValueError(f"SSO config file not found: {sso_config_path}")

        with sso_config_file.open(encoding="utf-8") as f:
            sso_file_config = yaml.safe_load(f)

        if sso_file_config:
            sso_overrides = overrides.setdefault("sso", {})
            self._merge_dict(sso_overrides, sso_file_config.get("sso", sso_file_config))
            resolution.record(
                "sso",
                f"loaded from {sso_config_path}",
                ParameterSource.CLI,
                origin="--sso-config",
            )

    def _merge_dict(self, target: dict[str, Any], source: dict[str, Any]) -> None:
        """Deep merge source dict into target dict."""
        for key, value in source.items():
            if (
                isinstance(value, dict)
                and key in target
                and isinstance(target[key], dict)
            ):
                self._merge_dict(target[key], value)
            else:
                target[key] = value

    def _apply_brute_force_settings(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply brute force protection settings."""
        brute_force_overrides: dict[str, Any] = {}

        if getattr(args, "brute_force_protection_enabled", None) is not None:
            brute_force_overrides["enabled"] = bool(args.brute_force_protection_enabled)
            resolution.record(
                "auth.brute_force_protection.enabled",
                brute_force_overrides["enabled"],
                ParameterSource.CLI,
                origin="--enable/disable-brute-force-protection",
            )

        if getattr(args, "auth_max_failed_attempts", None) is not None:
            brute_force_overrides["max_failed_attempts"] = max(
                1, int(args.auth_max_failed_attempts)
            )
            resolution.record(
                "auth.brute_force_protection.max_failed_attempts",
                brute_force_overrides["max_failed_attempts"],
                ParameterSource.CLI,
                origin="--auth-max-failed-attempts",
            )

        if getattr(args, "auth_brute_force_ttl", None) is not None:
            brute_force_overrides["ttl_seconds"] = max(
                1, int(args.auth_brute_force_ttl)
            )
            resolution.record(
                "auth.brute_force_protection.ttl_seconds",
                brute_force_overrides["ttl_seconds"],
                ParameterSource.CLI,
                origin="--auth-brute-force-ttl",
            )

        if getattr(args, "auth_initial_block_seconds", None) is not None:
            brute_force_overrides["initial_block_seconds"] = max(
                1, int(args.auth_initial_block_seconds)
            )
            resolution.record(
                "auth.brute_force_protection.initial_block_seconds",
                brute_force_overrides["initial_block_seconds"],
                ParameterSource.CLI,
                origin="--auth-brute-force-initial-block",
            )

        if getattr(args, "auth_block_multiplier", None) is not None:
            multiplier = float(args.auth_block_multiplier)
            brute_force_overrides["block_multiplier"] = (
                multiplier if multiplier > 1 else 1.0
            )
            resolution.record(
                "auth.brute_force_protection.block_multiplier",
                brute_force_overrides["block_multiplier"],
                ParameterSource.CLI,
                origin="--auth-brute-force-multiplier",
            )

        if getattr(args, "auth_max_block_seconds", None) is not None:
            brute_force_overrides["max_block_seconds"] = max(
                1, int(args.auth_max_block_seconds)
            )
            resolution.record(
                "auth.brute_force_protection.max_block_seconds",
                brute_force_overrides["max_block_seconds"],
                ParameterSource.CLI,
                origin="--auth-brute-force-max-block",
            )

        if brute_force_overrides:
            auth_overrides = overrides.setdefault("auth", {})
            auth_overrides["brute_force_protection"] = brute_force_overrides
