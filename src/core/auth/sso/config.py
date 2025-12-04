"""
Configuration models for SSO authentication.

This module defines the configuration structures for SSO authentication,
including provider configurations and authorization settings.
"""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class ProviderConfig:
    """Configuration for a single identity provider."""

    type: Literal["oauth2", "saml"]
    client_id: str
    client_secret: str
    enabled: bool = True  # Default: True (provider is enabled)
    discovery_url: str | None = None  # For OIDC
    metadata_url: str | None = None  # For SAML
    authorize_url: str | None = None  # Manual OAuth2
    token_url: str | None = None  # Manual OAuth2
    userinfo_url: str | None = None  # Manual OAuth2
    scopes: list[str] = field(default_factory=list)


@dataclass
class AuthorizationConfig:
    """Configuration for authorization after SSO."""

    mode: Literal["single_user", "enterprise"]

    # Enterprise mode settings
    api_url: str | None = None
    api_timeout: int = 30  # seconds

    # Single-user mode settings
    confirmation_code_expiry_minutes: int = 10
    max_confirmation_attempts: int = 3


@dataclass
class CaptchaConfig:
    """Configuration for bot protection on the public SSO form."""

    enabled: bool = False  # Default: disabled (requires site_key and secret_key)
    provider: Literal["cloudflare_turnstile"] = "cloudflare_turnstile"
    site_key: str | None = None
    secret_key: str | None = None
    verify_url: str = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
    widget_mode: Literal["invisible", "managed"] = "invisible"
    timeout_seconds: float = 5.0


@dataclass
class SSOConfig:
    """Configuration for SSO authentication."""

    enabled: bool = False
    session_lifetime_hours: int = 24  # How long SSO session is valid

    # OAuth2/OIDC/SAML providers
    providers: dict[str, ProviderConfig] = field(default_factory=dict)

    # Authorization configuration
    authorization: AuthorizationConfig = field(
        default_factory=lambda: AuthorizationConfig(mode="single_user")
    )

    # Database configuration
    database_path: str = "./var/sso_auth.db"

    # Captcha configuration
    captcha: CaptchaConfig = field(default_factory=CaptchaConfig)
