"""
Token service for SSO authentication.

This module provides secure token generation, hashing, and verification
using Argon2id with 2025-recommended security parameters.
"""

import base64
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from src.core.auth.sso.exceptions import TokenError


class TokenService:
    """
    Secure token generation and verification using Argon2id.

    This service generates cryptographically secure tokens with 256-bit entropy
    and hashes them using Argon2id with parameters meeting 2025 security standards:
    - Memory cost: 64 MB (65536 KiB)
    - Time cost (iterations): 3
    - Parallelism: 4
    """

    @classmethod
    def create_for_environment(cls) -> "TokenService":
        """
        Create TokenService with appropriate parameters for the current environment.

        Uses lightweight parameters (8MB memory, 1 iteration, 1 thread) during testing
        and production parameters (64MB memory, 3 iterations, 4 threads) otherwise.

        Returns:
            TokenService: Configured instance for the current environment
        """
        import os

        # Check if we're in a test environment
        is_test = os.getenv("PYTEST_CURRENT_TEST") is not None

        if is_test:
            # Fast parameters for testing (8 MB, 1 iteration, 1 thread)
            return cls(memory_cost=8192, time_cost=1, parallelism=1)
        else:
            # Production parameters (64 MB, 3 iterations, 4 threads)
            return cls()

    def __init__(
        self,
        memory_cost: int = 65536,  # 64 MB (production default)
        time_cost: int = 3,  # 3 iterations (production default)
        parallelism: int = 4,  # 4 threads (production default)
    ) -> None:
        """
        Initialize TokenService with Argon2id hasher.

        Args:
            memory_cost: Memory cost in KiB (default: 65536 = 64 MB for production)
            time_cost: Number of iterations (default: 3 for production)
            parallelism: Number of parallel threads (default: 4 for production)

        For testing, use lighter parameters to speed up tests:
            TokenService(memory_cost=8192, time_cost=1, parallelism=1)

        Production defaults use 2025-recommended security parameters:
        - memory_cost: 65536 (64 MB)
        - time_cost: 3 iterations
        - parallelism: 4 threads
        - hash_len: 32 bytes (fixed)
        - salt_len: 16 bytes (fixed)
        """
        self._hasher = PasswordHasher(
            memory_cost=memory_cost,
            time_cost=time_cost,
            parallelism=parallelism,
            hash_len=32,  # Always 32 bytes output
            salt_len=16,  # Always 16 bytes salt
        )

    def generate_token(self) -> tuple[str, str]:
        """
        Generate a new agent token with 256-bit entropy.

        The token is generated using cryptographically secure random bytes
        and encoded as base64url for Bearer token compatibility.

        Returns:
            tuple[str, str]: (plaintext_token, token_hash)
                - plaintext_token: Base64url-encoded token (43+ characters)
                - token_hash: Argon2id hash of the token

        Raises:
            TokenError: If token generation or hashing fails
        """
        try:
            # Generate 256 bits (32 bytes) of cryptographically secure random data
            token_bytes = secrets.token_bytes(32)

            # Encode as base64url (URL-safe, no padding)
            plaintext_token = (
                base64.urlsafe_b64encode(token_bytes).decode("ascii").rstrip("=")
            )

            # Hash the token using Argon2id
            token_hash = self.hash_token(plaintext_token)

            return plaintext_token, token_hash

        except Exception as e:
            raise TokenError(
                "Failed to generate token",
                details={"error": str(e)},
                original_error=e,
            ) from e

    def hash_token(self, token: str) -> str:
        """
        Hash a token using Argon2id.

        Args:
            token: The plaintext token to hash

        Returns:
            str: Argon2id hash string (includes algorithm, parameters, salt, and hash)

        Raises:
            TokenError: If hashing fails
        """
        try:
            return self._hasher.hash(token)
        except Exception as e:
            raise TokenError(
                "Failed to hash token",
                details={"error": str(e)},
                original_error=e,
            ) from e

    def verify_token(self, token: str, stored_hash: str) -> bool:
        """
        Verify token against stored hash using constant-time comparison.

        This method uses Argon2's built-in verification which performs
        constant-time comparison to prevent timing attacks.

        Args:
            token: The plaintext token to verify
            stored_hash: The Argon2id hash to verify against

        Returns:
            bool: True if token matches hash, False otherwise

        Raises:
            TokenError: If verification fails due to invalid hash format
        """
        try:
            # Argon2 verify() raises VerifyMismatchError if token doesn't match
            # This is expected behavior, not an error
            self._hasher.verify(stored_hash, token)
            return True

        except (VerifyMismatchError, VerificationError):
            # Token doesn't match - this is normal, return False
            return False

        except InvalidHashError as e:
            # Hash format is invalid - this is an error
            raise TokenError(
                "Invalid hash format",
                details={"error": str(e)},
                original_error=e,
            ) from e

        except Exception as e:
            # Unexpected error during verification
            raise TokenError(
                "Token verification failed",
                details={"error": str(e)},
                original_error=e,
            ) from e
