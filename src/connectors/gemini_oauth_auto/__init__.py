"""
Gemini OAuth Auto-Connector.

Self-contained OAuth2 authentication for Google Gemini API without external dependencies.
Provides multi-account support with automatic token refresh and round-robin account rotation.

Public exports:
- Models: StoredAccount, AccountSummary
- Services: TokenStorageService, TokenRefreshService, AccountSelectorService, OAuthFlowService
- Errors: OAuthError, TokenRefreshError, NoValidAccountsError
- Connector: GeminiOAuthAutoConnector (registered as "gemini-oauth-auto")
"""

# Models
from src.connectors.gemini_oauth_auto.account_selector import AccountSelectorService

# Connector (imports trigger registration with backend_registry)
from src.connectors.gemini_oauth_auto.connector import GeminiOAuthAutoConnector

# Errors
from src.connectors.gemini_oauth_auto.errors import (
    NoValidAccountsError,
    OAuthError,
    TokenRefreshError,
)

# Interfaces - for type hints and DI
from src.connectors.gemini_oauth_auto.interfaces import (
    IAccountSelector,
    ITokenRefresh,
    ITokenStorage,
)
from src.connectors.gemini_oauth_auto.models import AccountSummary, StoredAccount
from src.connectors.gemini_oauth_auto.oauth_flow import OAuthFlowService
from src.connectors.gemini_oauth_auto.token_refresh import TokenRefreshService

# Services
from src.connectors.gemini_oauth_auto.token_storage import TokenStorageService

__all__ = [
    # Models
    "StoredAccount",
    "AccountSummary",
    # Interfaces
    "ITokenStorage",
    "ITokenRefresh",
    "IAccountSelector",
    # Errors
    "OAuthError",
    "TokenRefreshError",
    "NoValidAccountsError",
    # Services
    "TokenStorageService",
    "TokenRefreshService",
    "AccountSelectorService",
    "OAuthFlowService",
    # Connector
    "GeminiOAuthAutoConnector",
]
