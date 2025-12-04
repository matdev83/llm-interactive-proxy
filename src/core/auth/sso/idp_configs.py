"""
Identity Provider specific configurations.

This module provides pre-configured settings for popular identity providers,
making it easy to integrate with Google, Microsoft, GitHub, LinkedIn, and AWS.
"""

from src.core.auth.sso.config import ProviderConfig


def create_google_config(
    client_id: str, client_secret: str, enabled: bool = True
) -> ProviderConfig:
    """
    Create Google OAuth2/OIDC provider configuration.

    Google supports OpenID Connect with automatic discovery.
    This configuration uses Google's OIDC discovery endpoint to automatically
    retrieve authorization, token, and userinfo endpoints.

    Required OAuth2 credentials:
    - Create credentials at: https://console.cloud.google.com/apis/credentials
    - OAuth 2.0 Client ID type: Web application
    - Authorized redirect URIs: Add your callback URL (e.g., http://localhost:8080/auth/callback)

    Scopes:
    - openid: Required for OIDC authentication
    - email: Access user's email address
    - profile: Access user's basic profile information

    Args:
        client_id: Google OAuth2 client ID
        client_secret: Google OAuth2 client secret

    Returns:
        ProviderConfig configured for Google OIDC

    Example:
        >>> config = create_google_config(
        ...     client_id="123456.apps.googleusercontent.com",
        ...     client_secret="GOCSPX-abc123"
        ... )
    """
    return ProviderConfig(
        type="oauth2",
        client_id=client_id,
        client_secret=client_secret,
        enabled=enabled,
        discovery_url="https://accounts.google.com/.well-known/openid-configuration",
        scopes=["openid", "email", "profile"],
    )


def create_microsoft_config(
    client_id: str,
    client_secret: str,
    tenant_id: str = "common",
    enabled: bool = True,
) -> ProviderConfig:
    """
    Create Microsoft Azure AD/Entra ID OAuth2/OIDC provider configuration.

    Microsoft Azure AD (now called Entra ID) supports OpenID Connect with
    automatic discovery. This configuration uses Microsoft's OIDC discovery
    endpoint to automatically retrieve authorization, token, and userinfo endpoints.

    Required OAuth2 credentials:
    - Create app registration at: https://portal.azure.com/#view/Microsoft_AAD_IAM/ActiveDirectoryMenuBlade/~/RegisteredApps
    - Platform: Web
    - Redirect URI: Add your callback URL (e.g., http://localhost:8080/auth/callback)
    - Client secret: Create in "Certificates & secrets" section

    Tenant ID options:
    - "common": Multi-tenant (personal and work/school accounts)
    - "organizations": Work/school accounts only
    - "consumers": Personal Microsoft accounts only
    - Specific tenant ID: Single tenant (e.g., "12345678-1234-1234-1234-123456789012")

    Scopes:
    - openid: Required for OIDC authentication
    - email: Access user's email address
    - profile: Access user's basic profile information

    Args:
        client_id: Azure AD application (client) ID
        client_secret: Azure AD client secret
        tenant_id: Azure AD tenant ID (default: "common" for multi-tenant)

    Returns:
        ProviderConfig configured for Microsoft Azure AD/Entra ID

    Example:
        >>> # Multi-tenant configuration
        >>> config = create_microsoft_config(
        ...     client_id="12345678-1234-1234-1234-123456789012",
        ...     client_secret="abc~123"
        ... )
        >>>
        >>> # Single-tenant configuration
        >>> config = create_microsoft_config(
        ...     client_id="12345678-1234-1234-1234-123456789012",
        ...     client_secret="abc~123",
        ...     tenant_id="87654321-4321-4321-4321-210987654321"
        ... )
    """
    discovery_url = (
        f"https://login.microsoftonline.com/{tenant_id}/v2.0/"
        ".well-known/openid-configuration"
    )

    return ProviderConfig(
        type="oauth2",
        client_id=client_id,
        client_secret=client_secret,
        enabled=enabled,
        discovery_url=discovery_url,
        scopes=["openid", "email", "profile"],
    )


def create_github_config(
    client_id: str, client_secret: str, enabled: bool = True
) -> ProviderConfig:
    """
    Create GitHub OAuth2 provider configuration.

    GitHub uses OAuth2 but does not support OpenID Connect discovery.
    This configuration manually specifies the authorization, token, and user
    endpoints required for GitHub authentication.

    Required OAuth2 credentials:
    - Create OAuth App at: https://github.com/settings/developers
    - Application name: Your application name
    - Homepage URL: Your application URL
    - Authorization callback URL: Your callback URL (e.g., http://localhost:8080/auth/callback)

    Scopes:
    - user:email: Access user's email addresses (required to get email)
    - read:user: Access user's profile information

    Note: GitHub may not expose user email if privacy settings restrict it.
    The SSO service will attempt to fetch email from the /user/emails endpoint.

    Args:
        client_id: GitHub OAuth App client ID
        client_secret: GitHub OAuth App client secret

    Returns:
        ProviderConfig configured for GitHub OAuth2

    Example:
        >>> config = create_github_config(
        ...     client_id="Iv1.abc123def456",
        ...     client_secret="abc123def456ghi789jkl012mno345pqr678stu"
        ... )
    """
    return ProviderConfig(
        type="oauth2",
        client_id=client_id,
        client_secret=client_secret,
        enabled=enabled,
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        userinfo_url="https://api.github.com/user",
        scopes=["user:email", "read:user"],
    )


def create_linkedin_config(
    client_id: str, client_secret: str, enabled: bool = True
) -> ProviderConfig:
    """
    Create LinkedIn OAuth2 provider configuration.

    LinkedIn uses OAuth2 but does not support OpenID Connect discovery.
    This configuration manually specifies the authorization and token endpoints.
    User information is retrieved via LinkedIn's v2 API.

    Required OAuth2 credentials:
    - Create app at: https://www.linkedin.com/developers/apps
    - Products: Add "Sign In with LinkedIn using OpenID Connect"
    - Authorized redirect URLs: Add your callback URL (e.g., http://localhost:8080/auth/callback)

    Scopes:
    - openid: Required for authentication
    - profile: Access user's basic profile
    - email: Access user's email address

    Note: LinkedIn's API requires specific headers (X-Restli-Protocol-Version: 2.0.0)
    which are handled by the SSO service's provider-specific extraction logic.

    Args:
        client_id: LinkedIn OAuth2 client ID
        client_secret: LinkedIn OAuth2 client secret

    Returns:
        ProviderConfig configured for LinkedIn OAuth2

    Example:
        >>> config = create_linkedin_config(
        ...     client_id="abc123def456",
        ...     client_secret="AbC123DeF456"
        ... )
    """
    return ProviderConfig(
        type="oauth2",
        client_id=client_id,
        client_secret=client_secret,
        enabled=enabled,
        authorize_url="https://www.linkedin.com/oauth/v2/authorization",
        token_url="https://www.linkedin.com/oauth/v2/accessToken",
        # LinkedIn userinfo is fetched via provider-specific logic in SSOService
        userinfo_url=None,
        scopes=["openid", "profile", "email"],
    )


def create_aws_iam_identity_center_config(
    client_id: str,
    client_secret: str,
    region: str = "us-east-1",
    enabled: bool = True,
    _start_url: str | None = None,
) -> ProviderConfig:
    """
    Create AWS IAM Identity Center (formerly AWS SSO) OIDC provider configuration.

    AWS IAM Identity Center supports OpenID Connect with automatic discovery.
    This configuration uses AWS's OIDC discovery endpoint to automatically
    retrieve authorization, token, and userinfo endpoints.

    Required setup:
    1. Enable IAM Identity Center in AWS Console
    2. Create an application:
       - Go to IAM Identity Center > Applications
       - Choose "Add application" > "I have an application I want to set up"
       - Application type: "OAuth 2.0"
       - Display name: Your application name
    3. Configure application:
       - Redirect URIs: Add your callback URL (e.g., http://localhost:8080/auth/callback)
       - Grant types: Authorization code
       - Scopes: openid, email, profile
    4. Note the Client ID and Client Secret from the application details

    Discovery URL format:
    - If you have a start URL (e.g., https://d-abc123.awsapps.com/start):
      The discovery URL is: https://oidc.{region}.amazonaws.com/
    - The start URL domain (d-abc123) is your Identity Center instance ID

    Args:
        client_id: AWS IAM Identity Center application client ID
        client_secret: AWS IAM Identity Center application client secret
        region: AWS region where Identity Center is configured (default: us-east-1)
        _start_url: Reserved for future use. Optional AWS SSO start URL
                   (e.g., https://d-abc123.awsapps.com/start)

    Returns:
        ProviderConfig configured for AWS IAM Identity Center OIDC

    Example:
        >>> # Using region-based discovery URL
        >>> config = create_aws_iam_identity_center_config(
        ...     client_id="abc123def456ghi789",
        ...     client_secret="AbC123DeF456GhI789JkL012",
        ...     region="us-west-2"
        ... )
        >>>
        >>> # Using start URL to derive discovery URL
        >>> config = create_aws_iam_identity_center_config(
        ...     client_id="abc123def456ghi789",
        ...     client_secret="AbC123DeF456GhI789JkL012",
        ...     start_url="https://d-abc123.awsapps.com/start"
        ... )

    Note:
        AWS IAM Identity Center OIDC endpoints follow the pattern:
        https://oidc.{region}.amazonaws.com/.well-known/openid-configuration

        If you have a start URL, the region is typically embedded in the URL
        or can be found in the IAM Identity Center settings.
    """
    # Construct discovery URL based on AWS region
    # AWS IAM Identity Center uses a regional OIDC endpoint
    discovery_url = (
        f"https://oidc.{region}.amazonaws.com/.well-known/openid-configuration"
    )

    return ProviderConfig(
        type="oauth2",
        client_id=client_id,
        client_secret=client_secret,
        enabled=enabled,
        discovery_url=discovery_url,
        scopes=["openid", "email", "profile"],
    )


# Convenience mapping for easy provider lookup
PROVIDER_FACTORIES = {
    "google": create_google_config,
    "microsoft": create_microsoft_config,
    "azure": create_microsoft_config,  # Alias for Microsoft
    "github": create_github_config,
    "linkedin": create_linkedin_config,
    "aws": create_aws_iam_identity_center_config,
    "aws-sso": create_aws_iam_identity_center_config,  # Alias for AWS
}


def create_provider_config(
    provider_name: str,
    client_id: str,
    client_secret: str,
    **kwargs,
) -> ProviderConfig:
    """
    Create a provider configuration using the provider name.

    This is a convenience function that looks up the appropriate factory
    function based on the provider name and creates the configuration.

    Supported providers:
    - google: Google OAuth2/OIDC
    - microsoft, azure: Microsoft Azure AD/Entra ID
    - github: GitHub OAuth2
    - linkedin: LinkedIn OAuth2
    - aws, aws-sso: AWS IAM Identity Center

    Args:
        provider_name: Name of the provider (case-insensitive)
        client_id: OAuth2 client ID
        client_secret: OAuth2 client secret
        **kwargs: Additional provider-specific arguments
                  (e.g., tenant_id for Microsoft, region for AWS)

    Returns:
        ProviderConfig for the specified provider

    Raises:
        ValueError: If provider_name is not supported

    Example:
        >>> # Google
        >>> config = create_provider_config(
        ...     "google",
        ...     client_id="123.apps.googleusercontent.com",
        ...     client_secret="secret"
        ... )
        >>>
        >>> # Microsoft with tenant
        >>> config = create_provider_config(
        ...     "microsoft",
        ...     client_id="12345678-1234-1234-1234-123456789012",
        ...     client_secret="secret",
        ...     tenant_id="common"
        ... )
        >>>
        >>> # AWS with region
        >>> config = create_provider_config(
        ...     "aws",
        ...     client_id="abc123",
        ...     client_secret="secret",
        ...     region="us-west-2"
        ... )
    """
    provider_key = provider_name.lower()

    if provider_key not in PROVIDER_FACTORIES:
        supported = ", ".join(sorted(set(PROVIDER_FACTORIES.keys())))
        raise ValueError(
            f"Unsupported provider: {provider_name}. "
            f"Supported providers: {supported}"
        )

    factory = PROVIDER_FACTORIES[provider_key]
    return factory(client_id, client_secret, **kwargs)  # type: ignore
