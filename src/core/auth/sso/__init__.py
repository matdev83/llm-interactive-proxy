"""
SSO (Single Sign-On) authentication module.

This module provides OAuth2 and SAML authentication support for the LLM Proxy,
enabling enterprise-ready authentication flows with support for multiple identity
providers including Google, Microsoft, GitHub, LinkedIn, and AWS IAM Identity Center.
"""

from src.core.auth.sso.config import (
    AuthorizationConfig,
    ProviderConfig,
    SSOConfig,
)
from src.core.auth.sso.database import (
    DatabaseManager,
    TokenRepository,
)
from src.core.auth.sso.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ConfigurationError,
    RateLimitError,
    SSOException,
    TokenError,
)
from src.core.auth.sso.middleware import AuthMiddleware
from src.core.auth.sso.models import (
    AuthorizationResult,
    ConfirmationResult,
    PendingAuthorization,
    RateLimitRecord,
    RateLimitResult,
    SSOResult,
    TokenRecord,
    TokenValidationResult,
)
from src.core.auth.sso.sandbox_handler import SandboxHandler
from src.core.auth.sso.token_service import TokenService

__all__ = [
    # Config
    "SSOConfig",
    "ProviderConfig",
    "AuthorizationConfig",
    # Database
    "DatabaseManager",
    "TokenRepository",
    # Services
    "TokenService",
    "SandboxHandler",
    "AuthMiddleware",
    # Models
    "TokenRecord",
    "PendingAuthorization",
    "RateLimitRecord",
    "SSOResult",
    "TokenValidationResult",
    "ConfirmationResult",
    "AuthorizationResult",
    "RateLimitResult",
    # Exceptions
    "SSOException",
    "AuthenticationError",
    "AuthorizationError",
    "ConfigurationError",
    "TokenError",
    "RateLimitError",
]
