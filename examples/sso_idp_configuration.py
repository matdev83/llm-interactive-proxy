"""
Example: Configuring Identity Providers for SSO Authentication

This script demonstrates how to programmatically configure identity providers
for SSO authentication using the idp_configs module.

Run with: python -m examples.sso_idp_configuration
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.auth.sso.config import AuthorizationConfig, CaptchaConfig, SSOConfig
from src.core.auth.sso.idp_configs import (
    create_google_config,
    create_microsoft_config,
    create_github_config,
    create_linkedin_config,
    create_aws_iam_identity_center_config,
    create_provider_config,
)


def example_google_configuration():
    """Example: Configure Google OAuth2/OIDC."""
    print("=== Google OAuth2/OIDC Configuration ===")

    # Create Google provider config
    google_config = create_google_config(
        client_id="123456789.apps.googleusercontent.com",
        client_secret="GOCSPX-abc123def456",
    )

    print(f"Provider type: {google_config.type}")
    print(f"Discovery URL: {google_config.discovery_url}")
    print(f"Scopes: {', '.join(google_config.scopes)}")
    print()


def example_microsoft_configuration():
    """Example: Configure Microsoft Azure AD/Entra ID."""
    print("=== Microsoft Azure AD/Entra ID Configuration ===")

    # Multi-tenant configuration (common)
    microsoft_config = create_microsoft_config(
        client_id="12345678-1234-1234-1234-123456789012",
        client_secret="abc~123def~456",
        tenant_id="common",  # Supports personal + work/school accounts
    )

    print(f"Provider type: {microsoft_config.type}")
    print(f"Discovery URL: {microsoft_config.discovery_url}")
    print(f"Scopes: {', '.join(microsoft_config.scopes)}")
    print()

    # Single-tenant configuration
    print("Single-tenant configuration:")
    single_tenant_config = create_microsoft_config(
        client_id="12345678-1234-1234-1234-123456789012",
        client_secret="abc~123def~456",
        tenant_id="87654321-4321-4321-4321-210987654321",
    )
    print(f"Discovery URL: {single_tenant_config.discovery_url}")
    print()


def example_github_configuration():
    """Example: Configure GitHub OAuth2."""
    print("=== GitHub OAuth2 Configuration ===")

    github_config = create_github_config(
        client_id="Iv1.abc123def456",
        client_secret="abc123def456ghi789jkl012mno345pqr678stu",
    )

    print(f"Provider type: {github_config.type}")
    print(f"Authorize URL: {github_config.authorize_url}")
    print(f"Token URL: {github_config.token_url}")
    print(f"Userinfo URL: {github_config.userinfo_url}")
    print(f"Scopes: {', '.join(github_config.scopes)}")
    print()


def example_linkedin_configuration():
    """Example: Configure LinkedIn OAuth2."""
    print("=== LinkedIn OAuth2 Configuration ===")

    linkedin_config = create_linkedin_config(
        client_id="abc123def456",
        client_secret="AbC123DeF456",
    )

    print(f"Provider type: {linkedin_config.type}")
    print(f"Authorize URL: {linkedin_config.authorize_url}")
    print(f"Token URL: {linkedin_config.token_url}")
    print(f"Scopes: {', '.join(linkedin_config.scopes)}")
    print()


def example_aws_configuration():
    """Example: Configure AWS IAM Identity Center."""
    print("=== AWS IAM Identity Center Configuration ===")

    # Configuration with region
    aws_config = create_aws_iam_identity_center_config(
        client_id="abc123def456ghi789",
        client_secret="AbC123DeF456GhI789JkL012",
        region="us-west-2",
    )

    print(f"Provider type: {aws_config.type}")
    print(f"Discovery URL: {aws_config.discovery_url}")
    print(f"Scopes: {', '.join(aws_config.scopes)}")
    print()

    # Configuration with start URL
    print("With start URL:")
    aws_config_with_url = create_aws_iam_identity_center_config(
        client_id="abc123def456ghi789",
        client_secret="AbC123DeF456GhI789JkL012",
        start_url="https://d-abc123.awsapps.com/start",
        region="us-east-1",
    )
    print(f"Discovery URL: {aws_config_with_url.discovery_url}")
    print()


def example_convenience_function():
    """Example: Using the convenience create_provider_config function."""
    print("=== Using create_provider_config Convenience Function ===")

    # Create Google config
    google = create_provider_config(
        "google",
        client_id="123.apps.googleusercontent.com",
        client_secret="secret",
    )
    print(f"Google: {google.discovery_url}")

    # Create Microsoft config with tenant
    microsoft = create_provider_config(
        "microsoft",
        client_id="12345678-1234-1234-1234-123456789012",
        client_secret="secret",
        tenant_id="organizations",
    )
    print(f"Microsoft: {microsoft.discovery_url}")

    # Create GitHub config
    github = create_provider_config(
        "github",
        client_id="Iv1.abc123",
        client_secret="secret",
    )
    print(f"GitHub: {github.authorize_url}")

    # Create AWS config with region
    aws = create_provider_config(
        "aws",
        client_id="abc123",
        client_secret="secret",
        region="eu-west-1",
    )
    print(f"AWS: {aws.discovery_url}")
    print()


def example_full_sso_config():
    """Example: Creating a complete SSO configuration with multiple providers."""
    print("=== Complete SSO Configuration ===")

    # Create SSO configuration
    sso_config = SSOConfig(
        enabled=True,
        session_lifetime_hours=24,
        database_path="./var/sso_auth.db",
        authorization=AuthorizationConfig(
            mode="single_user",
            confirmation_code_expiry_minutes=10,
            max_confirmation_attempts=3,
        ),
        captcha=CaptchaConfig(
            enabled=True,
            site_key="CF_TURNSTILE_SITE_KEY",
            secret_key="CF_TURNSTILE_SECRET_KEY",
        ),
        providers={
            "google": create_google_config(
                client_id="123.apps.googleusercontent.com",
                client_secret="GOCSPX-secret",
            ),
            "github": create_github_config(
                client_id="Iv1.abc123",
                client_secret="github_secret",
            ),
            "microsoft": create_microsoft_config(
                client_id="12345678-1234-1234-1234-123456789012",
                client_secret="azure_secret",
                tenant_id="common",
            ),
        },
    )

    print(f"SSO Enabled: {sso_config.enabled}")
    print(f"Session Lifetime: {sso_config.session_lifetime_hours} hours")
    print(f"Authorization Mode: {sso_config.authorization.mode}")
    print(f"Configured Providers: {', '.join(sso_config.providers.keys())}")
    print()

    # Show details for each provider
    for name, provider in sso_config.providers.items():
        print(f"\n{name.upper()}:")
        print(f"  Type: {provider.type}")
        if provider.discovery_url:
            print(f"  Discovery: {provider.discovery_url}")
        else:
            print(f"  Authorize: {provider.authorize_url}")
            print(f"  Token: {provider.token_url}")
        print(f"  Scopes: {', '.join(provider.scopes)}")


def main():
    """Run all examples."""
    example_google_configuration()
    example_microsoft_configuration()
    example_github_configuration()
    example_linkedin_configuration()
    example_aws_configuration()
    example_convenience_function()
    example_full_sso_config()


if __name__ == "__main__":
    main()
