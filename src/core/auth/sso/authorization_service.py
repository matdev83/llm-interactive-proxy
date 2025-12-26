"""
Authorization service for SSO authentication.

This module handles post-authentication authorization, including single-user
confirmation codes and enterprise authorization API integration.
"""

import hashlib
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from enum import Enum

import aiosqlite
import httpx

from src.core.auth.sso.config import AuthorizationConfig
from src.core.auth.sso.database import DatabaseManager
from src.core.auth.sso.exceptions import AuthorizationError
from src.core.auth.sso.models import (
    AuthorizationResult,
    ConfirmationResult,
)
from src.core.auth.sso.rate_limit_service import RateLimitService

logger = logging.getLogger(__name__)


class AuthorizationMode(str, Enum):
    """Authorization modes."""

    SINGLE_USER = "single_user"
    ENTERPRISE = "enterprise"


class AuthorizationService:
    """
    Manages authorization after successful SSO authentication.

    Handles confirmation code generation/verification for single-user mode
    and API queries for enterprise mode.
    """

    def __init__(
        self,
        mode: AuthorizationMode,
        config: AuthorizationConfig,
        database_manager: DatabaseManager,
        rate_limit_service: RateLimitService,
    ):
        """
        Initialize authorization service.

        Args:
            mode: Authorization mode (single_user or enterprise)
            config: Authorization configuration
            database_manager: Database manager for storing pending authorizations
            rate_limit_service: Service for rate limiting attempts
        """
        self.mode = mode
        self.config = config
        self.db_manager = database_manager
        self.rate_limit_service = rate_limit_service

    # =========================================================================
    # Single-User Mode
    # =========================================================================

    def generate_confirmation_code(self) -> str:
        """
        Generate a 6-digit secure random confirmation code.

        Returns:
            6-digit numeric string
        """
        # Generate a secure random number between 0 and 999999
        code_int = secrets.randbelow(1000000)
        # Format as 6-digit string with leading zeros
        return f"{code_int:06d}"

    def _hash_code(self, code: str) -> str:
        """
        Hash confirmation code for storage.

        Uses SHA-256 for speed (code is short-lived and low entropy anyway).
        Salt is not strictly necessary given the short lifetime and random nature,
        but we use a simple hash to avoid plaintext storage.

        Args:
            code: 6-digit code

        Returns:
            Hex digest of hash
        """
        return hashlib.sha256(code.encode("utf-8")).hexdigest()

    def log_confirmation_request(self, user_email: str, code: str) -> None:
        """
        Log confirmation code for user to see in console.

        Args:
            user_email: User's email address
            code: Generated confirmation code
        """
        # This is intentionally logged as WARNING to be visible in console
        logger.warning(
            f"\n"
            f"================================================================\n"
            f"SSO AUTHORIZATION REQUEST\n"
            f"User: {user_email}\n"
            f"Confirmation Code: {code}\n"
            f"Please enter this code in your browser to complete authorization.\n"
            f"================================================================"
        )

    async def create_pending_authorization(
        self,
        sso_state: str,
        user_email: str,
        user_id: str,
        provider: str,
        client_ip: str,
    ) -> None:
        """
        Create a pending authorization request and log the code.

        Args:
            sso_state: OAuth2 state parameter (used as session ID)
            user_email: User's email
            user_id: User's unique ID
            provider: Identity provider
            client_ip: Client IP address

        Raises:
            AuthorizationError: If creation fails
        """
        if self.mode != AuthorizationMode.SINGLE_USER:
            raise AuthorizationError("Not in single-user mode")

        code = self.generate_confirmation_code()
        code_hash = self._hash_code(code)
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=self.config.confirmation_code_expiry_minutes
        )

        try:
            async with aiosqlite.connect(self.db_manager.database_path) as db:
                await db.execute(
                    """
                    INSERT INTO pending_authorizations (
                        id, sso_state, user_email, user_id, provider,
                        confirmation_code_hash, attempts_remaining,
                        created_at, expires_at, client_ip
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        secrets.token_hex(16),  # Random ID
                        sso_state,
                        user_email,
                        user_id,
                        provider,
                        code_hash,
                        self.config.max_confirmation_attempts,
                        datetime.now(timezone.utc).isoformat(),
                        expires_at.isoformat(),
                        client_ip,
                    ),
                )
                await db.commit()

            # Log the code for the user
            self.log_confirmation_request(user_email, code)

        except Exception as e:
            raise AuthorizationError(
                "Failed to create pending authorization",
                details={"error": str(e)},
                original_error=e,
            ) from e

    async def verify_confirmation_code(
        self, sso_state: str, code: str, client_ip: str
    ) -> ConfirmationResult:
        """
        Verify user-entered confirmation code.

        Args:
            sso_state: OAuth2 state parameter (session ID)
            code: User-provided code
            client_ip: Client IP for rate limiting

        Returns:
            ConfirmationResult

        Raises:
            AuthorizationError: If database error occurs
        """
        if self.mode != AuthorizationMode.SINGLE_USER:
            raise AuthorizationError("Not in single-user mode")

        # Check rate limit first
        rate_result = await self.rate_limit_service.check_rate_limit(client_ip)
        if not rate_result.allowed:
            raise AuthorizationError(
                f"Rate limit exceeded. Try again in {rate_result.retry_after} seconds.",
                details={"retry_after": rate_result.retry_after},
            )

        try:
            async with aiosqlite.connect(self.db_manager.database_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """
                    SELECT * FROM pending_authorizations
                    WHERE sso_state = ?
                    """,
                    (sso_state,),
                )
                row = await cursor.fetchone()

                if not row:
                    # Record failed attempt on IP to prevent scanning
                    await self.rate_limit_service.record_failed_attempt(client_ip)
                    return ConfirmationResult(
                        success=False, attempts_remaining=0, must_reauthenticate=True
                    )

                # Check expiry
                # Parse the datetime and assume UTC if no timezone info
                expires_at = datetime.fromisoformat(row["expires_at"])
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) > expires_at:
                    # Expired
                    await db.execute(
                        "DELETE FROM pending_authorizations WHERE sso_state = ?",
                        (sso_state,),
                    )
                    await db.commit()
                    return ConfirmationResult(
                        success=False, attempts_remaining=0, must_reauthenticate=True
                    )

                # Check attempts
                attempts = row["attempts_remaining"]
                if attempts <= 0:
                    return ConfirmationResult(
                        success=False, attempts_remaining=0, must_reauthenticate=True
                    )

                # Verify code
                code_hash = self._hash_code(code)
                stored_hash = row["confirmation_code_hash"]

                # Use constant-time comparison for hash
                is_correct = secrets.compare_digest(stored_hash, code_hash)

                if is_correct:
                    # Success! Delete pending auth
                    await db.execute(
                        "DELETE FROM pending_authorizations WHERE sso_state = ?",
                        (sso_state,),
                    )
                    await db.commit()

                    # Reset rate limit for this IP
                    await self.rate_limit_service.reset_rate_limit(client_ip)

                    return ConfirmationResult(success=True, attempts_remaining=attempts)
                else:
                    # Failure. Decrement attempts.
                    new_attempts = attempts - 1
                    await db.execute(
                        """
                        UPDATE pending_authorizations
                        SET attempts_remaining = ?
                        WHERE sso_state = ?
                        """,
                        (new_attempts, sso_state),
                    )
                    await db.commit()

                    # Record rate limit failure
                    await self.rate_limit_service.record_failed_attempt(client_ip)

                    if new_attempts <= 0:
                        # Exhausted
                        return ConfirmationResult(
                            success=False,
                            attempts_remaining=0,
                            must_reauthenticate=True,
                        )
                    else:
                        return ConfirmationResult(
                            success=False,
                            attempts_remaining=new_attempts,
                            must_reauthenticate=False,
                        )

        except Exception as e:
            if isinstance(e, AuthorizationError):
                raise
            raise AuthorizationError(
                "Failed to verify confirmation code",
                details={"error": str(e)},
                original_error=e,
            ) from e

    # =========================================================================
    # Enterprise Mode
    # =========================================================================

    async def query_authorization_api(
        self, user_id: str, user_email: str, client_ip: str
    ) -> AuthorizationResult:
        """
        Query external authorization API (Enterprise mode).

        Args:
            user_id: User ID
            user_email: User email
            client_ip: Client IP address

        Returns:
            AuthorizationResult indicating success or failure

        Raises:
            AuthorizationError: If API call fails or returns invalid response
        """
        if self.mode != AuthorizationMode.ENTERPRISE:
            raise AuthorizationError("Not in enterprise mode")

        if not self.config.api_url:
            raise AuthorizationError("Authorization API URL not configured")

        payload = {
            "user_id": user_id,
            "user_email": user_email,
            "client_ip": client_ip,
        }

        try:
            async with httpx.AsyncClient(
                timeout=self.config.api_timeout, follow_redirects=True
            ) as client:
                response = await client.post(self.config.api_url, json=payload)

                if response.status_code != 200:
                    logger.error(
                        f"Authorization API returned status {response.status_code}: {response.text}"
                    )
                    return AuthorizationResult(
                        authorized=False,
                        error=f"API returned status {response.status_code}",
                    )

                # Parse response
                try:
                    data = response.json()
                    # Support {"authorized": bool} or just boolean/int in body if simple
                    if isinstance(data, bool):
                        authorized = data
                    elif isinstance(data, int):
                        authorized = bool(data)
                    elif isinstance(data, dict):
                        authorized = bool(data.get("authorized", False))
                    else:
                        logger.error(f"Unexpected API response format: {data}")
                        return AuthorizationResult(
                            authorized=False, error="Invalid response format"
                        )

                    return AuthorizationResult(authorized=authorized)

                except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
                    # Fallback: check if body is literally "true" or "1"
                    text = response.text.strip().lower()
                    if text in ("true", "1"):
                        return AuthorizationResult(authorized=True)
                    if text in ("false", "0"):
                        return AuthorizationResult(authorized=False)

                    logger.error(f"Failed to parse API response: {e}", exc_info=True)
                    return AuthorizationResult(
                        authorized=False, error="Failed to parse response"
                    )

        except httpx.TimeoutException:
            logger.error("Authorization API timed out")
            return AuthorizationResult(authorized=False, error="API timeout")
        except httpx.RequestError as e:
            logger.error(f"Authorization API request failed: {e}")
            return AuthorizationResult(authorized=False, error=f"Request failed: {e!s}")
        except Exception as e:
            logger.error(f"Unexpected error during authorization API query: {e}")
            return AuthorizationResult(
                authorized=False, error=f"Unexpected error: {e!s}"
            )
