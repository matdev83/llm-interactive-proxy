"""
Unit tests for strict JWKS verification.

Tests that ID token verification enforces JWKS requirement.
"""

import pytest
from src.core.auth.sso.config import AuthorizationConfig, ProviderConfig, SSOConfig
from src.core.auth.sso.exceptions import AuthenticationError
from src.core.auth.sso.sso_service import SSOService


@pytest.mark.asyncio
async def test_verify_id_token_rejects_missing_jwks():
    """
    Test that ID token verification rejects tokens when JWKS URI is missing.

    Requirement 11.4: Validate all tokens according to protocol specifications.
    Security: No fallback to unverified tokens.
    """
    config = SSOConfig(
        enabled=True,
        providers={
            "test": ProviderConfig(
                type="oauth2",
                client_id="test-client",
                client_secret="test-secret",
                authorize_url="https://example.com/authorize",
                token_url="https://example.com/token",
            )
        },
        authorization=AuthorizationConfig(mode="single_user"),
        database_path=":memory:",
    )

    service = SSOService(config)

    # Attempt to verify token without JWKS URI
    with pytest.raises(AuthenticationError) as exc_info:
        await service._verify_id_token(
            id_token="fake.jwt.token",
            jwks_uri=None,  # No JWKS URI
            client_id="test-client",
            issuer="https://example.com",
        )

    # Verify error message mentions JWKS requirement
    error_msg = str(exc_info.value)
    assert "JWKS URI" in error_msg or "jwks" in error_msg.lower()
    assert "verification requires" in error_msg or "required" in error_msg


@pytest.mark.asyncio
async def test_verify_id_token_error_details():
    """
    Test that missing JWKS error includes helpful details.
    """
    config = SSOConfig(
        enabled=True,
        providers={
            "test": ProviderConfig(
                type="oauth2",
                client_id="test-client",
                client_secret="test-secret",
                authorize_url="https://example.com/authorize",
                token_url="https://example.com/token",
            )
        },
        authorization=AuthorizationConfig(mode="single_user"),
        database_path=":memory:",
    )

    service = SSOService(config)

    # Attempt to verify token without JWKS URI
    with pytest.raises(AuthenticationError) as exc_info:
        await service._verify_id_token(
            id_token="fake.jwt.token",
            jwks_uri=None,
            client_id="test-client",
        )

    # Check error has details
    error = exc_info.value
    assert hasattr(error, "details")
    assert error.details.get("jwks_uri") is None


@pytest.mark.asyncio
async def test_verify_id_token_with_valid_jwks_uri(monkeypatch):
    """
    Test that ID token verification succeeds with valid JWKS URI.

    This ensures we didn't break the normal verification flow.
    """
    config = SSOConfig(
        enabled=True,
        providers={
            "test": ProviderConfig(
                type="oauth2",
                client_id="test-client",
                client_secret="test-secret",
                discovery_url="https://example.com/.well-known/openid-configuration",
            )
        },
        authorization=AuthorizationConfig(mode="single_user"),
        database_path=":memory:",
    )

    service = SSOService(config)

    # Mock JWKS fetch
    async def mock_fetch_jwks(jwks_uri):
        return {
            "keys": [
                {
                    "kty": "RSA",
                    "kid": "test-key",
                    "use": "sig",
                    "n": "test-n",
                    "e": "AQAB",
                }
            ]
        }

    # Mock JWT decode
    def mock_jwt_decode(token, key):
        return {
            "sub": "test-user",
            "aud": "test-client",
            "iss": "https://example.com",
            "exp": 9999999999,
        }

    monkeypatch.setattr(service, "_fetch_jwks", mock_fetch_jwks)
    monkeypatch.setattr(service._jwt, "decode", mock_jwt_decode)

    # Should succeed with JWKS URI
    claims = await service._verify_id_token(
        id_token="fake.jwt.token",
        jwks_uri="https://example.com/.well-known/jwks.json",
        client_id="test-client",
        issuer="https://example.com",
    )

    assert claims["sub"] == "test-user"
    assert claims["aud"] == "test-client"


@pytest.mark.asyncio
async def test_verify_id_token_fails_on_jwks_fetch_error():
    """
    Test that verification fails properly when JWKS fetch fails.

    Requirement 11.4: Proper error handling in token validation.
    """
    config = SSOConfig(
        enabled=True,
        providers={
            "test": ProviderConfig(
                type="oauth2",
                client_id="test-client",
                client_secret="test-secret",
                discovery_url="https://example.com/.well-known/openid-configuration",
            )
        },
        authorization=AuthorizationConfig(mode="single_user"),
        database_path=":memory:",
    )

    service = SSOService(config)

    # Attempt to verify with unreachable JWKS URI
    with pytest.raises(AuthenticationError) as exc_info:
        await service._verify_id_token(
            id_token="fake.jwt.token",
            jwks_uri="https://invalid-jwks-endpoint.example.com/jwks.json",
            client_id="test-client",
        )

    # Should fail with fetch error
    error_msg = str(exc_info.value)
    assert "Failed to fetch JWKS" in error_msg or "JWKS" in error_msg


def test_sso_service_documents_hot_reload_limitation():
    """
    Test that SSOService documents the hot-reload limitation.

    Requirement 13.5: Document configuration hot-reload status.
    """
    # Check docstring mentions hot-reload
    docstring = SSOService.__doc__
    assert docstring is not None
    assert "hot reload" in docstring.lower() or "hot-reload" in docstring.lower()
    assert "13.5" in docstring or "Requirement 13.5" in docstring.lower()
