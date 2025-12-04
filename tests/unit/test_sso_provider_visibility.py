"""
Unit tests for SSO provider visibility logic.

Tests the get_enabled_providers() and is_provider_enabled() methods
to ensure providers are correctly filtered based on configuration.
"""

from src.core.auth.sso.config import ProviderConfig, SSOConfig
from src.core.auth.sso.sso_service import SSOService


class TestProviderVisibility:
    """Test provider visibility and filtering logic."""

    def test_get_enabled_providers_all_enabled(self):
        """Test that all properly configured providers are returned when enabled."""
        config = SSOConfig(
            enabled=True,
            providers={
                "google": ProviderConfig(
                    type="oauth2",
                    client_id="google_id",
                    client_secret="google_secret",
                    enabled=True,
                    discovery_url="https://accounts.google.com/.well-known/openid-configuration",
                ),
                "github": ProviderConfig(
                    type="oauth2",
                    client_id="github_id",
                    client_secret="github_secret",
                    enabled=True,
                    authorize_url="https://github.com/login/oauth/authorize",
                    token_url="https://github.com/login/oauth/access_token",
                ),
            },
        )

        service = SSOService(config)
        enabled = service.get_enabled_providers()

        assert len(enabled) == 2
        assert "google" in enabled
        assert "github" in enabled

    def test_get_enabled_providers_some_disabled(self):
        """Test that explicitly disabled providers are excluded."""
        config = SSOConfig(
            enabled=True,
            providers={
                "google": ProviderConfig(
                    type="oauth2",
                    client_id="google_id",
                    client_secret="google_secret",
                    enabled=True,
                    discovery_url="https://accounts.google.com/.well-known/openid-configuration",
                ),
                "github": ProviderConfig(
                    type="oauth2",
                    client_id="github_id",
                    client_secret="github_secret",
                    enabled=False,  # Explicitly disabled
                    authorize_url="https://github.com/login/oauth/authorize",
                    token_url="https://github.com/login/oauth/access_token",
                ),
            },
        )

        service = SSOService(config)
        enabled = service.get_enabled_providers()

        assert len(enabled) == 1
        assert "google" in enabled
        assert "github" not in enabled

    def test_get_enabled_providers_missing_credentials(self):
        """Test that providers with missing credentials are excluded."""
        config = SSOConfig(
            enabled=True,
            providers={
                "google": ProviderConfig(
                    type="oauth2",
                    client_id="google_id",
                    client_secret="google_secret",
                    enabled=True,
                    discovery_url="https://accounts.google.com/.well-known/openid-configuration",
                ),
                "github": ProviderConfig(
                    type="oauth2",
                    client_id="",  # Missing client_id
                    client_secret="github_secret",
                    enabled=True,
                    authorize_url="https://github.com/login/oauth/authorize",
                    token_url="https://github.com/login/oauth/access_token",
                ),
            },
        )

        service = SSOService(config)
        enabled = service.get_enabled_providers()

        assert len(enabled) == 1
        assert "google" in enabled
        assert "github" not in enabled

    def test_get_enabled_providers_missing_endpoints(self):
        """Test that OAuth2 providers without discovery_url or authorize_url are excluded."""
        config = SSOConfig(
            enabled=True,
            providers={
                "google": ProviderConfig(
                    type="oauth2",
                    client_id="google_id",
                    client_secret="google_secret",
                    enabled=True,
                    discovery_url="https://accounts.google.com/.well-known/openid-configuration",
                ),
                "custom": ProviderConfig(
                    type="oauth2",
                    client_id="custom_id",
                    client_secret="custom_secret",
                    enabled=True,
                    # Missing both discovery_url and authorize_url
                ),
            },
        )

        service = SSOService(config)
        enabled = service.get_enabled_providers()

        assert len(enabled) == 1
        assert "google" in enabled
        assert "custom" not in enabled

    def test_is_provider_enabled_valid(self):
        """Test is_provider_enabled returns True for valid provider."""
        config = SSOConfig(
            enabled=True,
            providers={
                "google": ProviderConfig(
                    type="oauth2",
                    client_id="google_id",
                    client_secret="google_secret",
                    enabled=True,
                    discovery_url="https://accounts.google.com/.well-known/openid-configuration",
                ),
            },
        )

        service = SSOService(config)
        assert service.is_provider_enabled("google") is True

    def test_is_provider_enabled_disabled(self):
        """Test is_provider_enabled returns False for disabled provider."""
        config = SSOConfig(
            enabled=True,
            providers={
                "google": ProviderConfig(
                    type="oauth2",
                    client_id="google_id",
                    client_secret="google_secret",
                    enabled=False,
                    discovery_url="https://accounts.google.com/.well-known/openid-configuration",
                ),
            },
        )

        service = SSOService(config)
        assert service.is_provider_enabled("google") is False

    def test_is_provider_enabled_not_configured(self):
        """Test is_provider_enabled returns False for non-existent provider."""
        config = SSOConfig(enabled=True, providers={})

        service = SSOService(config)
        assert service.is_provider_enabled("google") is False

    def test_is_provider_enabled_missing_client_id(self):
        """Test is_provider_enabled returns False when client_id is missing."""
        config = SSOConfig(
            enabled=True,
            providers={
                "google": ProviderConfig(
                    type="oauth2",
                    client_id="",
                    client_secret="google_secret",
                    enabled=True,
                    discovery_url="https://accounts.google.com/.well-known/openid-configuration",
                ),
            },
        )

        service = SSOService(config)
        assert service.is_provider_enabled("google") is False

    def test_is_provider_enabled_missing_client_secret(self):
        """Test is_provider_enabled returns False when client_secret is missing."""
        config = SSOConfig(
            enabled=True,
            providers={
                "google": ProviderConfig(
                    type="oauth2",
                    client_id="google_id",
                    client_secret="",
                    enabled=True,
                    discovery_url="https://accounts.google.com/.well-known/openid-configuration",
                ),
            },
        )

        service = SSOService(config)
        assert service.is_provider_enabled("google") is False

    def test_is_provider_enabled_oauth2_with_authorize_url(self):
        """Test is_provider_enabled returns True for OAuth2 with manual authorize_url."""
        config = SSOConfig(
            enabled=True,
            providers={
                "github": ProviderConfig(
                    type="oauth2",
                    client_id="github_id",
                    client_secret="github_secret",
                    enabled=True,
                    authorize_url="https://github.com/login/oauth/authorize",
                    token_url="https://github.com/login/oauth/access_token",
                ),
            },
        )

        service = SSOService(config)
        assert service.is_provider_enabled("github") is True

    def test_is_provider_enabled_oauth2_missing_endpoints(self):
        """Test is_provider_enabled returns False for OAuth2 without discovery_url or authorize_url."""
        config = SSOConfig(
            enabled=True,
            providers={
                "custom": ProviderConfig(
                    type="oauth2",
                    client_id="custom_id",
                    client_secret="custom_secret",
                    enabled=True,
                    # Missing both discovery_url and authorize_url
                ),
            },
        )

        service = SSOService(config)
        assert service.is_provider_enabled("custom") is False

    def test_get_enabled_providers_empty_config(self):
        """Test get_enabled_providers returns empty list when no providers configured."""
        config = SSOConfig(enabled=True, providers={})

        service = SSOService(config)
        enabled = service.get_enabled_providers()

        assert len(enabled) == 0

    def test_get_enabled_providers_all_five_providers(self):
        """Test that all five supported providers can be enabled simultaneously."""
        config = SSOConfig(
            enabled=True,
            providers={
                "google": ProviderConfig(
                    type="oauth2",
                    client_id="google_id",
                    client_secret="google_secret",
                    enabled=True,
                    discovery_url="https://accounts.google.com/.well-known/openid-configuration",
                ),
                "microsoft": ProviderConfig(
                    type="oauth2",
                    client_id="microsoft_id",
                    client_secret="microsoft_secret",
                    enabled=True,
                    discovery_url="https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration",
                ),
                "github": ProviderConfig(
                    type="oauth2",
                    client_id="github_id",
                    client_secret="github_secret",
                    enabled=True,
                    authorize_url="https://github.com/login/oauth/authorize",
                    token_url="https://github.com/login/oauth/access_token",
                ),
                "linkedin": ProviderConfig(
                    type="oauth2",
                    client_id="linkedin_id",
                    client_secret="linkedin_secret",
                    enabled=True,
                    authorize_url="https://www.linkedin.com/oauth/v2/authorization",
                    token_url="https://www.linkedin.com/oauth/v2/accessToken",
                ),
                "aws": ProviderConfig(
                    type="oauth2",
                    client_id="aws_id",
                    client_secret="aws_secret",
                    enabled=True,
                    discovery_url="https://oidc.us-east-1.amazonaws.com/.well-known/openid-configuration",
                ),
            },
        )

        service = SSOService(config)
        enabled = service.get_enabled_providers()

        assert len(enabled) == 5
        assert "google" in enabled
        assert "microsoft" in enabled
        assert "github" in enabled
        assert "linkedin" in enabled
        assert "aws" in enabled
