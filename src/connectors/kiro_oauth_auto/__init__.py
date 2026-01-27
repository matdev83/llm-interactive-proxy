"""
Kiro OAuth Auto-Connector.

Self-contained OAuth2 authentication for Amazon Kiro / Amazon Q Developer streaming APIs.

Public exports:
- Models: StoredAccount, AccountSummary, KiroOAuthAutoConfig
- Services: TokenStorageService, TokenRefreshService, AccountSelectorService, OAuthFlowService
- Errors: OAuthError, TokenRefreshError, NoValidAccountsError
- Connector: KiroOAuthAutoConnector (registered as "kiro-oauth-auto")
"""

from src.connectors.kiro_oauth_auto.account_selector import AccountSelectorService
from src.connectors.kiro_oauth_auto.connector import KiroOAuthAutoConnector
from src.connectors.kiro_oauth_auto.errors import (
    NoValidAccountsError,
    OAuthError,
    TokenRefreshError,
)
from src.connectors.kiro_oauth_auto.models import (
    AccountSummary,
    KiroOAuthAutoConfig,
    StoredAccount,
)
from src.connectors.kiro_oauth_auto.oauth_flow import OAuthFlowService
from src.connectors.kiro_oauth_auto.token_refresh import TokenRefreshService
from src.connectors.kiro_oauth_auto.token_storage import TokenStorageService

__all__ = [
    "StoredAccount",
    "AccountSummary",
    "KiroOAuthAutoConfig",
    "OAuthError",
    "TokenRefreshError",
    "NoValidAccountsError",
    "TokenStorageService",
    "TokenRefreshService",
    "AccountSelectorService",
    "OAuthFlowService",
    "KiroOAuthAutoConnector",
]
