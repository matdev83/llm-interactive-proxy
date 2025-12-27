"""
SSO (Single Sign-On) authentication module.

This module provides OAuth2 and SAML authentication support for the LLM Proxy,
enabling enterprise-ready authentication flows with support for multiple identity
providers including Google, Microsoft, GitHub, LinkedIn, and AWS IAM Identity Center.
"""

from src.core.auth.sso.authorization_service import (
    AuthorizationMode,
    AuthorizationService,
)
from src.core.auth.sso.captcha_service import CaptchaService, CaptchaVerificationResult
from src.core.auth.sso.config import (
    AuthorizationConfig,
    CaptchaConfig,
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
from src.core.auth.sso.idp_configs import (
    PROVIDER_FACTORIES,
    create_aws_iam_identity_center_config,
    create_github_config,
    create_google_config,
    create_linkedin_config,
    create_microsoft_config,
    create_provider_config,
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
from src.core.auth.sso.rate_limit_service import RateLimitService
from src.core.auth.sso.sandbox_handler import SandboxHandler
from src.core.auth.sso.sso_service import SSOService
from src.core.auth.sso.startup_validation import (
    AuthenticationMode,
    StartupValidator,
    validate_startup_configuration,
)
from src.core.auth.sso.state_store import StateStore

__all__ = [
    # Config
    "SSOConfig",
    "ProviderConfig",
    "AuthorizationConfig",
    "CaptchaConfig",
    # IdP Configurations
    "create_google_config",
    "create_microsoft_config",
    "create_github_config",
    "create_linkedin_config",
    "create_aws_iam_identity_center_config",
    "create_provider_config",
    "PROVIDER_FACTORIES",
    # Web Interface
    "create_sso_router",
    # Internal state management
    "StateStore",
    # Services
    "SSOService",
    # Database
    "DatabaseManager",
    "TokenRepository",
    # Services
    "TokenService",
    "CaptchaService",
    "CaptchaVerificationResult",
    "SandboxHandler",
    "AuthMiddleware",
    "RateLimitService",
    "AuthorizationService",
    "AuthorizationMode",
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
    # Startup Validation
    "AuthenticationMode",
    "StartupValidator",
    "validate_startup_configuration",
]
