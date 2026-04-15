"""Access mode validation service.

Validates access mode configuration rules during proxy startup to ensure
security boundaries are properly enforced for Single User Mode and Multi User Mode.

Requirements satisfied:
- 2.1-2.4: Single User Mode localhost enforcement
- 4.1-4.3: Single User Mode optional authentication
- 5.1-5.6: Multi User Mode authentication enforcement
- 7.1-7.4: Multi User Mode OAuth flag rejection
- 8.1-8.3: Multi User Mode OAuth auto-replacement rejection
- 9.1-9.5: Multi User Mode desktop notification rejection
- 11.1-11.4: Error messages and user guidance
"""

from __future__ import annotations

import argparse

from src.core.config.app_config import AppConfig


class AccessModeValidator:
    """Service for validating access mode configuration rules.

    Validates that access mode settings are consistent with other configuration
    values such as host binding, authentication settings, OAuth flags, and
    notification settings. Raises ValueError with actionable error messages
    when validation fails.
    """

    # OAuth debugging override flags that are blocked in Multi User Mode
    OAUTH_DEBUGGING_FLAGS = [
        "enable_gemini_oauth_auto_backend_debugging_override",
        "enable_gemini_oauth_free_backend_debugging_override",
        "enable_gemini_oauth_plan_backend_debugging_override",
        "enable_qwen_oauth_backend_debugging_override",
        "enable_opencode_zen_backend_debugging_override",
        "enable_kiro_oauth_auto_backend_debugging_override",
        "enable_openai_codex_backend_debugging_override",
    ]

    def validate(self, config: AppConfig, args: argparse.Namespace) -> None:
        """Validate access mode configuration rules.

        Checks all access mode validation rules:
        - Single User Mode requires localhost binding
        - Multi User Mode requires authentication for non-localhost
        - Multi User Mode blocks OAuth debugging override flags
        - Multi User Mode blocks OAuth auto-replacement flag
        - Multi User Mode blocks desktop notifications

        Args:
            config: The application configuration containing access mode settings
            args: Parsed command-line arguments namespace

        Raises:
            ValueError: If validation fails, with detailed error message containing:
                - What validation rule failed
                - Current configuration value that caused the failure
                - Actionable guidance on how to resolve the issue
                - References to relevant CLI flags or configuration options
        """
        access_mode = config.access_mode

        if access_mode.is_single_user():
            self._validate_single_user_mode(config, args)
        elif access_mode.is_multi_user():
            self._validate_multi_user_mode(config, args)

    def _validate_single_user_mode(
        self, config: AppConfig, args: argparse.Namespace
    ) -> None:
        """Validate Single User Mode configuration rules.

        Single User Mode requirements:
        - Must bind to 127.0.0.1 only
        - OAuth flags are allowed
        - OAuth auto-replacement is allowed
        - Notifications are allowed

        Args:
            config: Application configuration
            args: Parsed CLI arguments

        Raises:
            ValueError: If validation fails
        """
        if config.host != "127.0.0.1":
            raise ValueError(
                f"Single User Mode requires binding to 127.0.0.1 only. "
                f"Current host: {config.host}. "
                f"Use --multi-user-mode for remote access."
            )

    def _validate_multi_user_mode(
        self, config: AppConfig, args: argparse.Namespace
    ) -> None:
        """Validate Multi User Mode configuration rules.

        Multi User Mode requirements:
        - If binding to non-localhost, authentication must be enabled
        - OAuth debugging override flags are blocked
        - OAuth auto-replacement flag is blocked
        - Desktop notifications are blocked

        Args:
            config: Application configuration
            args: Parsed CLI arguments

        Raises:
            ValueError: If validation fails
        """
        # Check authentication requirement for non-localhost
        if config.host != "127.0.0.1" and not self._is_authentication_enabled(config):
            raise ValueError(
                f"Multi User Mode requires authentication when binding to non-localhost addresses. "
                f"Current host: {config.host}. "
                f"Enable authentication via API keys (--api-key) or SSO."
            )

        # Check OAuth debugging override flags
        oauth_flags_found = []
        for flag_name in self.OAUTH_DEBUGGING_FLAGS:
            if getattr(args, flag_name, False):
                oauth_flags_found.append(flag_name)

        if oauth_flags_found:
            flag_names_str = ", ".join(
                f"--{flag.replace('_', '-')}" for flag in oauth_flags_found
            )
            raise ValueError(
                f"OAuth debugging override flags are not allowed in Multi User Mode: {flag_names_str}. "
                f"OAuth connectors are blocked in production deployments."
            )

        # Check OAuth auto-replacement flag
        if getattr(args, "allow_oauth_auto_replacement", False):
            raise ValueError(
                "OAuth auto-replacement (--allow-oauth-auto-replacement) is not allowed in Multi User Mode. "
                "OAuth connectors are blocked in production deployments."
            )

        # Check desktop notifications
        if config.notifications.is_enabled(config.host):
            raise ValueError(
                "Desktop notifications are not allowed in Multi User Mode. "
                "Multi User Mode is for dedicated servers, not desktop computers. "
                "Use --disable-notifications or switch to Single User Mode."
            )

    def _is_authentication_enabled(self, config: AppConfig) -> bool:
        """Check if authentication is enabled.

        Authentication is considered enabled if:
        - Auth is not disabled (disable_auth=False), OR
        - SSO is configured and enabled

        Args:
            config: Application configuration

        Returns:
            True if authentication is enabled, False otherwise
        """
        # Check if auth is explicitly disabled
        if config.auth.disable_auth:
            # Even if auth is disabled, SSO can still provide authentication
            return config.sso is not None and getattr(config.sso, "enabled", False)

        # Auth is enabled (not disabled)
        return True
