"""
Data models for SSO authentication.

This module defines the data structures used for token storage,
authorization tracking, and rate limiting.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class TokenRecord:
    """Database record for an agent token."""

    id: str  # UUID
    token_hash: str  # Argon2id hash
    user_id: str  # SSO user identifier
    user_email: str  # User email from SSO
    provider: str  # IdP that authenticated user
    is_authenticated: bool  # Current SSO session status
    is_active: bool  # False if revoked
    created_at: datetime  # Token creation time
    last_authenticated_at: datetime | None  # Last successful SSO
    auth_expires_at: datetime | None  # SSO session expiry


@dataclass
class PendingAuthorization:
    """Tracks pending authorization requests (single-user mode)."""

    id: str  # UUID
    sso_state: str  # OAuth2 state parameter
    user_email: str  # Email from SSO
    user_id: str  # User ID from SSO
    provider: str  # IdP name
    confirmation_code_hash: str  # 6-digit code (hashed)
    attempts_remaining: int  # Starts at 3
    created_at: datetime  # Request creation time
    expires_at: datetime  # Code expiry (e.g., 10 minutes)
    client_ip: str  # For audit logging


@dataclass
class RateLimitRecord:
    """Tracks rate limiting for brute-force protection."""

    identifier: str  # IP address or session ID
    failed_attempts: int  # Consecutive failures
    last_attempt_at: datetime  # Last attempt timestamp
    blocked_until: datetime | None  # Exponential backoff


@dataclass
class SSOResult:
    """Result from SSO authentication callback."""

    success: bool
    user_id: str | None = None
    user_email: str | None = None
    provider: str | None = None
    error: str | None = None


@dataclass
class TokenValidationResult:
    """Result from token validation."""

    is_valid: bool
    user_id: str | None = None
    is_authenticated: bool = False
    token_id: str | None = None  # For session linking


@dataclass
class ConfirmationResult:
    """Result from confirmation code verification."""

    success: bool
    attempts_remaining: int
    must_reauthenticate: bool = False


@dataclass
class AuthorizationResult:
    """Result from authorization API query."""

    authorized: bool
    error: str | None = None


@dataclass
class RateLimitResult:
    """Result from rate limit check."""

    allowed: bool
    retry_after: int = 0  # seconds until retry allowed


@dataclass
class JWK:
    """Represents a JSON Web Key (JWK)."""

    kty: str
    alg: str | None = None
    use: str | None = None
    kid: str | None = None
    n: str | None = None
    e: str | None = None
    x: str | None = None
    y: str | None = None
    crv: str | None = None


@dataclass
class JWKS:
    """Represents a JSON Web Key Set (JWKS)."""

    keys: list[JWK]


@dataclass
class SAMLMetadata:
    """Parsed SAML metadata information."""

    sso_redirect_url: str | None
    signing_cert: str | None
    entity_id: str | None
