"""
Unit tests for IdP-specific configurations.

Tests the factory functions that create provider configurations for
Google, Microsoft, GitHub, LinkedIn, and AWS IAM Identity Center.
"""

import pytest
from src.core.auth.sso.idp_configs import (
    PROVIDER_FACTORIES,
    create_aws_iam_identity_center_config,
    create_github_config,
    create_google_config,
    create_linkedin_config,
    create_microsoft_config,
    create_provider_config,
)


class TestGoogleConfig:
    """Tests for Google OAuth2/OIDC configuration."""

    def test_create_google_config_basic(self):
        """Test creating basic Google configuration."""
        config = create_google_config(
            client_id="test.apps.googleusercontent.com",
            client_secret="test_secret",
        )

        assert config.type == "oauth2"
        assert config.client_id == "test.apps.googleusercontent.com"
        assert config.client_secret == "test_secret"
        assert (
            config.discovery_url
            == "https://accounts.google.com/.well-known/openid-configuration"
        )
        assert config.scopes == ["openid", "email", "profile"]

    def test_google_config_uses_oidc_discovery(self):
        """Test that Google config uses OIDC discovery."""
        config = create_google_config("id", "secret")

        assert config.discovery_url is not None
        assert config.authorize_url is None
        assert config.token_url is None


class TestMicrosoftConfig:
    """Tests for Microsoft Azure AD/Entra ID configuration."""

    def test_create_microsoft_config_default_tenant(self):
        """Test creating Microsoft config with default tenant (common)."""
        config = create_microsoft_config(
            client_id="12345678-1234-1234-1234-123456789012",
            client_secret="test_secret",
        )

        assert config.type == "oauth2"
        assert config.client_id == "12345678-1234-1234-1234-123456789012"
        assert config.client_secret == "test_secret"
        assert "common" in config.discovery_url
        assert config.scopes == ["openid", "email", "profile"]

    def test_create_microsoft_config_specific_tenant(self):
        """Test creating Microsoft config with specific tenant ID."""
        tenant_id = "87654321-4321-4321-4321-210987654321"
        config = create_microsoft_config(
            client_id="12345678-1234-1234-1234-123456789012",
            client_secret="test_secret",
            tenant_id=tenant_id,
        )

        assert tenant_id in config.discovery_url
        assert config.discovery_url == (
            f"https://login.microsoftonline.com/{tenant_id}/v2.0/"
            ".well-known/openid-configuration"
        )

    def test_create_microsoft_config_organizations_tenant(self):
        """Test creating Microsoft config with 'organizations' tenant."""
        config = create_microsoft_config(
            client_id="test_id",
            client_secret="test_secret",
            tenant_id="organizations",
        )

        assert "organizations" in config.discovery_url

    def test_microsoft_config_uses_oidc_discovery(self):
        """Test that Microsoft config uses OIDC discovery."""
        config = create_microsoft_config("id", "secret")

        assert config.discovery_url is not None
        assert config.authorize_url is None
        assert config.token_url is None


class TestGitHubConfig:
    """Tests for GitHub OAuth2 configuration."""

    def test_create_github_config_basic(self):
        """Test creating basic GitHub configuration."""
        config = create_github_config(
            client_id="Iv1.abc123def456",
            client_secret="test_secret",
        )

        assert config.type == "oauth2"
        assert config.client_id == "Iv1.abc123def456"
        assert config.client_secret == "test_secret"
        assert config.authorize_url == "https://github.com/login/oauth/authorize"
        assert config.token_url == "https://github.com/login/oauth/access_token"
        assert config.userinfo_url == "https://api.github.com/user"
        assert config.scopes == ["user:email", "read:user"]

    def test_github_config_uses_manual_endpoints(self):
        """Test that GitHub config uses manual endpoints (not discovery)."""
        config = create_github_config("id", "secret")

        assert config.discovery_url is None
        assert config.authorize_url is not None
        assert config.token_url is not None
        assert config.userinfo_url is not None


class TestLinkedInConfig:
    """Tests for LinkedIn OAuth2 configuration."""

    def test_create_linkedin_config_basic(self):
        """Test creating basic LinkedIn configuration."""
        config = create_linkedin_config(
            client_id="abc123def456",
            client_secret="test_secret",
        )

        assert config.type == "oauth2"
        assert config.client_id == "abc123def456"
        assert config.client_secret == "test_secret"
        assert config.authorize_url == "https://www.linkedin.com/oauth/v2/authorization"
        assert config.token_url == "https://www.linkedin.com/oauth/v2/accessToken"
        assert config.userinfo_url is None  # LinkedIn uses provider-specific API
        assert config.scopes == ["openid", "profile", "email"]

    def test_linkedin_config_uses_manual_endpoints(self):
        """Test that LinkedIn config uses manual endpoints."""
        config = create_linkedin_config("id", "secret")

        assert config.discovery_url is None
        assert config.authorize_url is not None
        assert config.token_url is not None


class TestAWSConfig:
    """Tests for AWS IAM Identity Center configuration."""

    def test_create_aws_config_default_region(self):
        """Test creating AWS config with default region."""
        config = create_aws_iam_identity_center_config(
            client_id="test_id",
            client_secret="test_secret",
        )

        assert config.type == "oauth2"
        assert config.client_id == "test_id"
        assert config.client_secret == "test_secret"
        assert "us-east-1" in config.discovery_url
        assert config.scopes == ["openid", "email", "profile"]

    def test_create_aws_config_custom_region(self):
        """Test creating AWS config with custom region."""
        config = create_aws_iam_identity_center_config(
            client_id="test_id",
            client_secret="test_secret",
            region="eu-west-1",
        )

        assert "eu-west-1" in config.discovery_url
        assert config.discovery_url == (
            "https://oidc.eu-west-1.amazonaws.com/.well-known/openid-configuration"
        )

    def test_create_aws_config_with_start_url(self):
        """Test creating AWS config with start URL."""
        config = create_aws_iam_identity_center_config(
            client_id="test_id",
            client_secret="test_secret",
            start_url="https://d-abc123.awsapps.com/start",
            region="us-west-2",
        )

        # Start URL is informational, region is used for discovery
        assert "us-west-2" in config.discovery_url

    def test_aws_config_uses_oidc_discovery(self):
        """Test that AWS config uses OIDC discovery."""
        config = create_aws_iam_identity_center_config("id", "secret")

        assert config.discovery_url is not None
        assert config.authorize_url is None
        assert config.token_url is None


class TestProviderConfigConvenience:
    """Tests for the convenience create_provider_config function."""

    def test_create_google_via_convenience(self):
        """Test creating Google config via convenience function."""
        config = create_provider_config(
            "google",
            client_id="test_id",
            client_secret="test_secret",
        )

        assert config.type == "oauth2"
        assert "google" in config.discovery_url.lower()

    def test_create_microsoft_via_convenience(self):
        """Test creating Microsoft config via convenience function."""
        config = create_provider_config(
            "microsoft",
            client_id="test_id",
            client_secret="test_secret",
            tenant_id="organizations",
        )

        assert config.type == "oauth2"
        assert "organizations" in config.discovery_url

    def test_create_azure_alias(self):
        """Test that 'azure' is an alias for Microsoft."""
        config = create_provider_config(
            "azure",
            client_id="test_id",
            client_secret="test_secret",
        )

        assert config.type == "oauth2"
        assert "microsoftonline" in config.discovery_url

    def test_create_github_via_convenience(self):
        """Test creating GitHub config via convenience function."""
        config = create_provider_config(
            "github",
            client_id="test_id",
            client_secret="test_secret",
        )

        assert config.type == "oauth2"
        assert "github" in config.authorize_url

    def test_create_linkedin_via_convenience(self):
        """Test creating LinkedIn config via convenience function."""
        config = create_provider_config(
            "linkedin",
            client_id="test_id",
            client_secret="test_secret",
        )

        assert config.type == "oauth2"
        assert "linkedin" in config.authorize_url

    def test_create_aws_via_convenience(self):
        """Test creating AWS config via convenience function."""
        config = create_provider_config(
            "aws",
            client_id="test_id",
            client_secret="test_secret",
            region="ap-southeast-1",
        )

        assert config.type == "oauth2"
        assert "ap-southeast-1" in config.discovery_url

    def test_create_aws_sso_alias(self):
        """Test that 'aws-sso' is an alias for AWS."""
        config = create_provider_config(
            "aws-sso",
            client_id="test_id",
            client_secret="test_secret",
        )

        assert config.type == "oauth2"
        assert "amazonaws.com" in config.discovery_url

    def test_case_insensitive_provider_name(self):
        """Test that provider names are case-insensitive."""
        config1 = create_provider_config("GOOGLE", "id", "secret")
        config2 = create_provider_config("Google", "id", "secret")
        config3 = create_provider_config("google", "id", "secret")

        assert config1.discovery_url == config2.discovery_url == config3.discovery_url

    def test_unsupported_provider_raises_error(self):
        """Test that unsupported provider raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            create_provider_config(
                "unsupported_provider",
                client_id="test_id",
                client_secret="test_secret",
            )

        assert "unsupported_provider" in str(exc_info.value).lower()
        assert "supported providers" in str(exc_info.value).lower()


class TestProviderFactories:
    """Tests for the PROVIDER_FACTORIES mapping."""

    def test_all_providers_in_factories(self):
        """Test that all expected providers are in PROVIDER_FACTORIES."""
        expected_providers = {
            "google",
            "microsoft",
            "azure",
            "github",
            "linkedin",
            "aws",
            "aws-sso",
        }

        assert set(PROVIDER_FACTORIES.keys()) == expected_providers

    def test_factories_return_callable(self):
        """Test that all factories are callable."""
        for name, factory in PROVIDER_FACTORIES.items():
            assert callable(factory), f"Factory for {name} is not callable"

    def test_factories_create_valid_configs(self):
        """Test that all factories create valid ProviderConfig objects."""
        for name, factory in PROVIDER_FACTORIES.items():
            # Skip aliases for this test
            if name in ["azure", "aws-sso"]:
                continue

            config = factory("test_id", "test_secret")
            assert config.type == "oauth2"
            assert config.client_id == "test_id"
            assert config.client_secret == "test_secret"
            assert len(config.scopes) > 0
