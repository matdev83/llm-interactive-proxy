"""
Startup validation and mode switching for SSO authentication.

This module handles authentication mode detection and startup validation
to ensure the proxy is configured correctly before accepting requests.
"""

import logging
from dataclasses import dataclass
from typing import Literal

from src.core.auth.sso.config import SSOConfig
from src.core.auth.sso.exceptions import ConfigurationError

logger = logging.getLogger(__name__)


@dataclass
class AuthenticationMode:
    """Represents the detected authentication mode."""

    mode: Literal["sso", "legacy", "no_auth"]
    sso_config: SSOConfig | None = None
    legacy_api_keys: list[str] | None = None


class StartupValidator:
    """Validates authentication configuration at startup."""

    def __init__(
        self,
        host: str,
        sso_config: SSOConfig | None = None,
        legacy_api_keys: list[str] | None = None,
        disable_auth: bool = False,
    ):
        """
        Initialize the startup validator.

        Args:
            host: The host address the proxy will bind to
            sso_config: SSO configuration if SSO mode is enabled
            legacy_api_keys: Legacy API keys if configured
            disable_auth: Whether authentication is explicitly disabled
        """
        self.host = host
        self.sso_config = sso_config
        self.legacy_api_keys = legacy_api_keys or []
        self.disable_auth = disable_auth

    def detect_authentication_mode(self) -> AuthenticationMode:
        """
        Detect the authentication mode based on configuration.

        Returns:
            AuthenticationMode indicating the detected mode

        Validates: Requirements 1.1
        """
        # Check if SSO is explicitly enabled
        if self.sso_config is not None and self.sso_config.enabled:
            logger.info("SSO authentication mode detected")
            return AuthenticationMode(
                mode="sso",
                sso_config=self.sso_config,
            )

        # Check if legacy API keys are configured
        if self.legacy_api_keys:
            logger.info("Legacy authentication mode detected")
            return AuthenticationMode(
                mode="legacy",
                legacy_api_keys=self.legacy_api_keys,
            )

        # No authentication configured
        logger.info("No authentication mode detected")
        return AuthenticationMode(mode="no_auth")

    def validate_sso_mode(self, mode: AuthenticationMode) -> None:
        """
        Validate SSO mode configuration.

        Args:
            mode: The detected authentication mode

        Raises:
            ConfigurationError: If SSO mode is invalid

        Validates: Requirements 1.2
        """
        if mode.mode != "sso":
            return

        # In SSO mode, legacy API keys should not be present
        if self.legacy_api_keys:
            raise ConfigurationError(
                "Legacy API keys are not allowed when SSO authentication is enabled. "
                "Please remove API_KEYS or auth.api_keys from configuration."
            )

        # Validate SSO configuration
        if mode.sso_config is None:
            raise ConfigurationError("SSO mode enabled but no SSO configuration found")

        if not mode.sso_config.providers:
            raise ConfigurationError(
                "SSO mode enabled but no identity providers configured"
            )

        if mode.sso_config.captcha and mode.sso_config.captcha.enabled:
            captcha_config = mode.sso_config.captcha
            if not captcha_config.site_key or not captcha_config.secret_key:
                raise ConfigurationError(
                    "Captcha is enabled for the SSO login form but site_key or secret_key is missing",
                )

        logger.info("SSO mode validation passed")

    def validate_no_auth_mode(self, mode: AuthenticationMode) -> None:
        """
        Validate no-auth mode configuration.

        Args:
            mode: The detected authentication mode

        Raises:
            ConfigurationError: If no-auth mode is invalid

        Validates: Requirements 1.4
        """
        if mode.mode != "no_auth":
            return

        # Check if binding to non-loopback address
        if not self._is_loopback_address(self.host):
            raise ConfigurationError(
                f"Cannot start proxy on non-loopback address '{self.host}' without authentication. "
                "Please enable SSO authentication or bind to 127.0.0.1/::1."
            )

        logger.info("No-auth mode validation passed (loopback binding)")

    def _is_loopback_address(self, host: str) -> bool:
        """
        Check if the host is a loopback address.

        Args:
            host: The host address to check

        Returns:
            True if the host is a loopback address
        """
        loopback_addresses = {
            "127.0.0.1",
            "localhost",
            "::1",
            "0:0:0:0:0:0:0:1",
        }
        return host.lower() in loopback_addresses

    def validate_startup(self) -> AuthenticationMode:
        """
        Validate the authentication configuration at startup.

        Returns:
            AuthenticationMode indicating the validated mode

        Raises:
            ConfigurationError: If the configuration is invalid
        """
        # Detect authentication mode
        mode = self.detect_authentication_mode()

        # Validate based on mode
        if mode.mode == "sso":
            self.validate_sso_mode(mode)
        elif mode.mode == "no_auth":
            self.validate_no_auth_mode(mode)

        return mode


def validate_startup_configuration(
    host: str,
    sso_config: SSOConfig | None = None,
    legacy_api_keys: list[str] | None = None,
    disable_auth: bool = False,
) -> AuthenticationMode:
    """
    Validate startup configuration and return authentication mode.

    Args:
        host: The host address the proxy will bind to
        sso_config: SSO configuration if SSO mode is enabled
        legacy_api_keys: Legacy API keys if configured
        disable_auth: Whether authentication is explicitly disabled

    Returns:
        AuthenticationMode indicating the validated mode

    Raises:
        ConfigurationError: If the configuration is invalid
    """
    validator = StartupValidator(
        host=host,
        sso_config=sso_config,
        legacy_api_keys=legacy_api_keys,
        disable_auth=disable_auth,
    )
    return validator.validate_startup()
