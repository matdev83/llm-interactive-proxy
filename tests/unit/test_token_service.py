"""Unit tests for TokenService.

These tests verify the basic functionality of token generation,
hashing, and verification.
"""

import pytest
from src.core.auth.sso.exceptions import TokenError
from src.core.auth.sso.token_service import TokenService


class TestTokenService:
    """Unit tests for TokenService."""

    def test_generate_token_returns_tuple(self) -> None:
        """Test that generate_token returns a tuple of (token, hash)."""
        service = TokenService()
        result = service.generate_token()

        assert isinstance(result, tuple)
        assert len(result) == 2

        plaintext_token, token_hash = result
        assert isinstance(plaintext_token, str)
        assert isinstance(token_hash, str)

    def test_generated_token_has_sufficient_length(self) -> None:
        """Test that generated tokens have at least 43 characters."""
        service = TokenService()
        plaintext_token, _ = service.generate_token()

        assert len(plaintext_token) >= 43

    def test_generated_token_is_base64url(self) -> None:
        """Test that generated tokens use base64url encoding."""
        service = TokenService()
        plaintext_token, _ = service.generate_token()

        # Base64url uses: A-Z, a-z, 0-9, -, _
        valid_chars = set(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        )
        assert all(c in valid_chars for c in plaintext_token)

    def test_token_hash_is_argon2id_format(self) -> None:
        """Test that token hashes are in Argon2id format."""
        service = TokenService()
        _, token_hash = service.generate_token()

        assert token_hash.startswith("$argon2id$")

    def test_verify_token_with_correct_token(self) -> None:
        """Test that verify_token returns True for correct token."""
        service = TokenService()
        plaintext_token, token_hash = service.generate_token()

        assert service.verify_token(plaintext_token, token_hash) is True

    def test_verify_token_with_incorrect_token(self) -> None:
        """Test that verify_token returns False for incorrect token."""
        service = TokenService()
        plaintext_token, token_hash = service.generate_token()

        # Modify the token slightly
        wrong_token = plaintext_token + "x"

        assert service.verify_token(wrong_token, token_hash) is False

    def test_verify_token_with_invalid_hash_format(self) -> None:
        """Test that verify_token raises TokenError for invalid hash format."""
        service = TokenService()
        plaintext_token, _ = service.generate_token()

        invalid_hash = "not-a-valid-hash"

        with pytest.raises(TokenError) as exc_info:
            service.verify_token(plaintext_token, invalid_hash)

        assert "Invalid hash format" in str(exc_info.value)

    def test_hash_token_produces_different_hashes(self) -> None:
        """Test that hashing the same token multiple times produces different hashes."""
        service = TokenService()
        plaintext_token, _ = service.generate_token()

        # Hash the same token multiple times
        hash1 = service.hash_token(plaintext_token)
        hash2 = service.hash_token(plaintext_token)
        hash3 = service.hash_token(plaintext_token)

        # All hashes should be different (due to random salt)
        assert hash1 != hash2
        assert hash2 != hash3
        assert hash1 != hash3

        # But all should verify correctly
        assert service.verify_token(plaintext_token, hash1) is True
        assert service.verify_token(plaintext_token, hash2) is True
        assert service.verify_token(plaintext_token, hash3) is True

    def test_generated_tokens_are_unique(self) -> None:
        """Test that multiple generated tokens are unique."""
        service = TokenService()

        tokens = set()
        for _ in range(100):
            plaintext_token, _ = service.generate_token()
            tokens.add(plaintext_token)

        # All 100 tokens should be unique
        assert len(tokens) == 100

    def test_token_hash_does_not_contain_plaintext(self) -> None:
        """Test that token hash does not contain the plaintext token."""
        service = TokenService()
        plaintext_token, token_hash = service.generate_token()

        # Hash should not contain the plaintext token
        assert plaintext_token not in token_hash

    def test_token_hash_is_longer_than_plaintext(self) -> None:
        """Test that token hash is longer than plaintext token."""
        service = TokenService()
        plaintext_token, token_hash = service.generate_token()

        # Hash includes algorithm, version, parameters, salt, and hash
        # so it should be significantly longer
        assert len(token_hash) > len(plaintext_token)

    def test_argon2id_parameters_meet_2025_standards(self) -> None:
        """Test that Argon2id parameters meet 2025 security standards."""
        service = TokenService()
        _, token_hash = service.generate_token()

        # Parse hash format: $argon2id$v=19$m=X,t=Y,p=Z$salt$hash
        parts = token_hash.split("$")
        params_str = parts[3]

        params = {}
        for param in params_str.split(","):
            key, value = param.split("=")
            params[key] = int(value)

        # Verify 2025 security parameters
        assert params["m"] >= 65536  # Memory >= 64 MB
        assert params["t"] >= 3  # Iterations >= 3
        assert params["p"] >= 4  # Parallelism >= 4
