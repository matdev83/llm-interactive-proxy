"""
Authentication middleware for SSO.

This module provides the AuthMiddleware class that intercepts incoming
requests, validates Bearer tokens, and enforces authentication requirements.
"""

from datetime import datetime
from typing import Any

from src.core.auth.sso.database import TokenRepository
from src.core.auth.sso.models import TokenValidationResult
from src.core.auth.sso.sandbox_handler import SandboxHandler
from src.core.auth.sso.token_service import TokenService


class AuthMiddleware:
    """Middleware that validates Bearer tokens and enforces authentication."""

    def __init__(
        self,
        token_service: TokenService,
        token_repository: TokenRepository,
        sandbox_handler: SandboxHandler,
    ):
        """
        Initialize authentication middleware.

        Args:
            token_service: Service for token verification
            token_repository: Repository for token storage
            sandbox_handler: Handler for unauthenticated responses
        """
        self.token_service = token_service
        self.token_repository = token_repository
        self.sandbox_handler = sandbox_handler

    def extract_bearer_token(self, request: dict[str, Any]) -> str | None:
        """
        Extract Bearer token from Authorization header.

        Handles missing and malformed headers gracefully by returning None.

        Args:
            request: Request dictionary containing headers

        Returns:
            Extracted token string, or None if not found or malformed
        """
        # Get headers from request
        headers = request.get("headers", {})

        # Authorization header can be in different cases
        auth_header = None
        for key in headers:
            if key.lower() == "authorization":
                auth_header = headers[key]
                break

        if not auth_header:
            return None

        # Check for Bearer scheme
        if not isinstance(auth_header, str):
            return None

        parts = auth_header.split()
        if len(parts) != 2:
            return None

        scheme, token = parts
        if scheme.lower() != "bearer":
            return None

        return token

    async def validate_token(self, token: str) -> TokenValidationResult:
        """
        Validate token against stored hashes.

        Checks if the token exists in the database and verifies its
        authentication status and expiry.

        Args:
            token: Bearer token to validate

        Returns:
            TokenValidationResult with validation details
        """
        # Get all active token hashes from database
        try:
            token_hashes = await self.token_repository.get_all_token_hashes()
        except Exception:
            # If database query fails, token is invalid
            return TokenValidationResult(is_valid=False)

        # Verify token against each hash using constant-time comparison
        token_record = None
        for stored_hash in token_hashes:
            try:
                if self.token_service.verify_token(token, stored_hash):
                    # Token matches this hash - fetch the full record
                    token_record = await self.token_repository.find_by_hash(stored_hash)
                    break
            except Exception:
                # If verification fails, continue to next hash
                continue

        if token_record is None:
            # Token not found in database
            return TokenValidationResult(is_valid=False)

        # Check if token is active
        if not token_record.is_active:
            return TokenValidationResult(is_valid=False)

        # Check if SSO session has expired
        from datetime import timezone

        now = datetime.now(timezone.utc)

        # Handle both offset-aware and offset-naive datetimes from DB
        if token_record.auth_expires_at:
            expires_at = token_record.auth_expires_at
            if expires_at.tzinfo is None:
                # Assume UTC if naive
                expires_at = expires_at.replace(tzinfo=timezone.utc)

            if expires_at < now:
                # Session expired - mark as unauthenticated
                await self.token_repository.update_auth_status(
                    token_record.id,
                    authenticated=False,
                    expiry=None,
                )
                return TokenValidationResult(
                    is_valid=True,
                    user_id=token_record.user_id,
                    is_authenticated=False,
                    token_id=token_record.id,
                )

        # Token is valid
        return TokenValidationResult(
            is_valid=True,
            user_id=token_record.user_id,
            is_authenticated=token_record.is_authenticated,
            token_id=token_record.id,
        )

    def detect_sandbox_history(self, messages: list[dict[str, Any]]) -> bool:
        """
        Check if conversation history contains sandbox login banner.

        This delegates to the SandboxHandler's detection logic.

        Args:
            messages: List of conversation messages to check

        Returns:
            True if sandbox content detected (session must be rejected)
        """
        return self.sandbox_handler.detect_sandbox_history(messages)

    async def __call__(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """
        Process incoming request for authentication.

        Args:
            request: Request dictionary

        Returns:
            None if authenticated (continue to next handler)
            Sandbox response dict if unauthenticated
        """
        # Extract Bearer token
        token = self.extract_bearer_token(request)

        # If no token, return sandbox response
        if token is None:
            return await self.sandbox_handler.generate_login_banner()

        # Validate token
        validation_result = await self.validate_token(token)

        # If token is invalid, return sandbox response
        if not validation_result.is_valid:
            return await self.sandbox_handler.generate_login_banner()

        # Check if SSO session is authenticated
        if not validation_result.is_authenticated:
            # Session expired or not yet authenticated
            # Return sandbox with re-authentication instructions
            # Pass token_id so the re-auth flow can update the existing token
            return await self.sandbox_handler.generate_login_banner(
                agent_token_id=validation_result.token_id
            )

        # Check conversation history for sandbox content
        messages = request.get("messages", [])
        if self.detect_sandbox_history(messages):
            # Sandbox session detected - reject and return new sandbox
            return await self.sandbox_handler.generate_login_banner()

        # Token is valid and authenticated - allow request to proceed
        return None
