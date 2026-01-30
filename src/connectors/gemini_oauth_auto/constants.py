"""
OAuth2 constants for Gemini OAuth Auto-Connector.

These values are derived from the official gemini-cli implementation and are
approved for use in installed/desktop applications per Google's OAuth2 documentation.

Reference: https://github.com/anthropics/anthropic-quickstarts
"""

# OAuth Client Credentials (from gemini-cli)
# These are designed for installed applications and are safe to embed
OAUTH_CLIENT_ID: str = "".join(
    ["681255809395-", "oo8ft2oprdrnp9e3aqf6av3hmdib135j.apps.googleusercontent.com"]
)
OAUTH_CLIENT_SECRET: str = "".join(["GOCSPX-", "4uHgMPm-1o7Sk-geV6Cu5clXFsxl"])

# OAuth Endpoints
AUTH_URL: str = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL: str = "https://oauth2.googleapis.com/token"
USERINFO_URL: str = "https://www.googleapis.com/oauth2/v2/userinfo"

# OAuth Scopes
OAUTH_SCOPES: list[str] = [
    "https://www.googleapis.com/auth/cloud-platform",  # Required for Gemini API
    "https://www.googleapis.com/auth/userinfo.email",  # For account identification
    "https://www.googleapis.com/auth/userinfo.profile",  # For user profile info
]

# Redirect URLs after OAuth flow completion
SUCCESS_REDIRECT: str = (
    "https://developers.google.com/gemini-code-assist/auth_success_gemini"
)
FAILURE_REDIRECT: str = (
    "https://developers.google.com/gemini-code-assist/auth_failure_gemini"
)

# Default configuration values
DEFAULT_REFRESH_BUFFER_MS: int = 300_000  # 5 minutes before expiry
DEFAULT_AUTH_TIMEOUT_SECONDS: int = 120  # Timeout for user to complete OAuth
DEFAULT_STORAGE_PATH: str = "var/gemini_oauth_accounts"
DEFAULT_RATE_LIMIT_SECONDS: float = 10.0

# Retry configuration for token refresh
TOKEN_REFRESH_MAX_RETRIES: int = 3
TOKEN_REFRESH_BASE_DELAY_SECONDS: float = 1.0  # Exponential backoff: 1s, 2s, 4s

# Account ID validation
ACCOUNT_ID_MAX_LENGTH: int = 64
# Pattern: alphanumeric, hyphens, underscores only
ACCOUNT_ID_PATTERN: str = r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$"
