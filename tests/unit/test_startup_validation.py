"""
Unit tests for SSO startup validation.
"""

import pytest
from src.core.auth.sso.config import AuthorizationConfig, ProviderConfig, SSOConfig
from src.core.auth.sso.exceptions import ConfigurationError
from src.core.auth.sso.startup_validation import (
    StartupValidator,
    validate_startup_configuration,
)


class TestStartupValidator:
    """Test the StartupValidator class."""

    def test_detect_sso_mode(self):
        """Test SSO mode detection."""
        sso_config = SSOConfig(
            enabled=True,
            providers={
                "google": ProviderConfig(
                    type="oauth2",
                    client_id="test-client-id",
                    client_secret="test-client-secret",
                    discovery_url="https://accounts.google.com/.well-known/openid-configuration",
                )
            },
            authorization=AuthorizationConfig(mode="single_user"),
        )

        validator = StartupValidator(
            host="127.0.0.1",
            sso_config=sso_config,
        )

        mode = validator.detect_authentication_mode()
        assert mode.mode == "sso"
        assert mode.sso_config is not None

    def test_detect_legacy_mode(self):
        """Test legacy mode detection."""
        validator = StartupValidator(
            host="127.0.0.1",
            legacy_api_keys=["key1", "key2"],
        )

        mode = validator.detect_authentication_mode()
        assert mode.mode == "legacy"
        assert mode.legacy_api_keys == ["key1", "key2"]

    def test_detect_no_auth_mode(self):
        """Test no-auth mode detection."""
        validator = StartupValidator(
            host="127.0.0.1",
        )

        mode = validator.detect_authentication_mode()
        assert mode.mode == "no_auth"

    def test_sso_mode_rejects_legacy_keys(self):
        """Test that SSO mode rejects legacy API keys."""
        sso_config = SSOConfig(
            enabled=True,
            providers={
                "google": ProviderConfig(
                    type="oauth2",
                    client_id="test-client-id",
                    client_secret="test-client-secret",
                )
            },
            authorization=AuthorizationConfig(mode="single_user"),
        )

        validator = StartupValidator(
            host="127.0.0.1",
            sso_config=sso_config,
            legacy_api_keys=["key1"],
        )

        with pytest.raises(ConfigurationError) as exc_info:
            validator.validate_startup()

        assert "legacy" in str(exc_info.value).lower()

    def test_non_loopback_requires_auth(self):
        """Test that non-loopback addresses require authentication."""
        validator = StartupValidator(
            host="0.0.0.0",
        )

        with pytest.raises(ConfigurationError) as exc_info:
            validator.validate_startup()

        assert "loopback" in str(exc_info.value).lower()

    def test_loopback_addresses(self):
        """Test that loopback addresses are recognized."""
        loopback_addresses = ["127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1"]

        for addr in loopback_addresses:
            validator = StartupValidator(host=addr)
            assert validator._is_loopback_address(addr)

    def test_non_loopback_addresses(self):
        """Test that non-loopback addresses are recognized."""
        non_loopback_addresses = [
            "0.0.0.0",
            "192.168.1.1",
            "10.0.0.1",
            "8.8.8.8",
        ]

        for addr in non_loopback_addresses:
            validator = StartupValidator(host=addr)
            assert not validator._is_loopback_address(addr)

    def test_sso_without_providers_fails(self):
        """Test that SSO without providers fails validation."""
        sso_config = SSOConfig(
            enabled=True,
            providers={},  # No providers
            authorization=AuthorizationConfig(mode="single_user"),
        )

        validator = StartupValidator(
            host="127.0.0.1",
            sso_config=sso_config,
        )

        with pytest.raises(ConfigurationError) as exc_info:
            validator.validate_startup()

        assert "provider" in str(exc_info.value).lower()


class TestValidateStartupConfiguration:
    """Test the validate_startup_configuration function."""

    def test_valid_sso_configuration(self):
        """Test valid SSO configuration."""
        sso_config = SSOConfig(
            enabled=True,
            providers={
                "google": ProviderConfig(
                    type="oauth2",
                    client_id="test-client-id",
                    client_secret="test-client-secret",
                )
            },
            authorization=AuthorizationConfig(mode="single_user"),
        )

        mode = validate_startup_configuration(
            host="127.0.0.1",
            sso_config=sso_config,
        )

        assert mode.mode == "sso"

    def test_valid_legacy_configuration(self):
        """Test valid legacy configuration."""
        mode = validate_startup_configuration(
            host="127.0.0.1",
            legacy_api_keys=["key1", "key2"],
        )

        assert mode.mode == "legacy"

    def test_valid_no_auth_configuration(self):
        """Test valid no-auth configuration on loopback."""
        mode = validate_startup_configuration(
            host="127.0.0.1",
        )

        assert mode.mode == "no_auth"

    def test_invalid_no_auth_on_non_loopback(self):
        """Test invalid no-auth configuration on non-loopback."""
        with pytest.raises(ConfigurationError):
            validate_startup_configuration(
                host="0.0.0.0",
            )
