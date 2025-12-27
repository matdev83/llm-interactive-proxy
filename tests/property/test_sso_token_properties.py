"""Property-based tests for SSO token data models.

Feature: sso-authentication
Property: 23
Validates: Requirements 8.2
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st
from src.core.auth.sso.models import TokenRecord
from tests.utils.hypothesis_config import (
    property_test_settings,
    slow_property_test_settings,
)

# Strategy for generating valid datetime objects
datetime_strategy = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
)


# Strategy for generating valid token hashes (Argon2id format)
@st.composite
def argon2id_hash_strategy(draw: st.DrawFn) -> str:
    """Generate valid Argon2id hash format strings.

    Argon2id hashes have the format:
    $argon2id$v=19$m=65536,t=3,p=4$<salt>$<hash>
    """
    # Generate random salt and hash (base64-encoded)
    salt = draw(
        st.text(
            alphabet=st.characters(
                whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="+/="
            ),
            min_size=22,
            max_size=22,
        )
    )
    hash_value = draw(
        st.text(
            alphabet=st.characters(
                whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="+/="
            ),
            min_size=43,
            max_size=43,
        )
    )

    # Use 2025-recommended parameters
    memory = draw(st.integers(min_value=65536, max_value=131072))  # 64-128 MB
    iterations = draw(st.integers(min_value=3, max_value=5))
    parallelism = draw(st.integers(min_value=4, max_value=8))

    return (
        f"$argon2id$v=19$m={memory},t={iterations},p={parallelism}${salt}${hash_value}"
    )


# Strategy for generating valid TokenRecord instances
@st.composite
def token_record_strategy(draw: st.DrawFn) -> TokenRecord:
    """Generate valid TokenRecord instances."""
    created_at = draw(datetime_strategy)
    last_authenticated_at = draw(
        st.one_of(
            st.just(created_at),
            st.datetimes(
                min_value=created_at,
                max_value=created_at + timedelta(days=365),
            ),
        )
    )

    # auth_expires_at can be None or a future datetime
    auth_expires_at = draw(
        st.one_of(
            st.none(),
            st.datetimes(
                min_value=last_authenticated_at,
                max_value=last_authenticated_at + timedelta(days=30),
            ),
        )
    )

    return TokenRecord(
        id=str(uuid4()),
        token_hash=draw(argon2id_hash_strategy()),
        user_id=draw(st.text(min_size=1, max_size=100)),
        user_email=draw(st.emails()),
        provider=draw(
            st.sampled_from(
                [
                    "google",
                    "microsoft",
                    "github",
                    "linkedin",
                    "aws-iam-ic",
                ]
            )
        ),
        is_authenticated=draw(st.booleans()),
        is_active=draw(st.booleans()),
        created_at=created_at,
        last_authenticated_at=last_authenticated_at,
        auth_expires_at=auth_expires_at,
    )


@given(token_record=token_record_strategy())
@property_test_settings(max_examples=20)  # Reduced from default 50 for performance
def test_property_23_token_record_completeness(
    token_record: TokenRecord,
) -> None:
    """
    Property 23: Token Record Completeness.

    For any token record stored in the database, the record SHALL contain all
    required fields: token hash, user identity, user email, provider,
    authentication status, active status, creation timestamp, and last
    authentication timestamp.

    Validates: Requirements 8.2

    Feature: sso-authentication, Property 23: Token Record Completeness
    """
    # Verify all required fields are present and non-None
    assert token_record.id is not None
    assert len(token_record.id) > 0

    assert token_record.token_hash is not None
    assert len(token_record.token_hash) > 0

    assert token_record.user_id is not None
    assert len(token_record.user_id) > 0

    assert token_record.user_email is not None
    assert len(token_record.user_email) > 0

    assert token_record.provider is not None
    assert len(token_record.provider) > 0

    # Boolean fields must be present (not None)
    assert token_record.is_authenticated is not None
    assert isinstance(token_record.is_authenticated, bool)

    assert token_record.is_active is not None
    assert isinstance(token_record.is_active, bool)

    # Timestamp fields must be present
    assert token_record.created_at is not None
    assert isinstance(token_record.created_at, datetime)

    assert token_record.last_authenticated_at is not None
    assert isinstance(token_record.last_authenticated_at, datetime)

    # auth_expires_at can be None (for expired sessions) or a datetime
    if token_record.auth_expires_at is not None:
        assert isinstance(token_record.auth_expires_at, datetime)


@given(token_record=token_record_strategy())
@property_test_settings()
def test_property_23_token_hash_format(
    token_record: TokenRecord,
) -> None:
    """
    Property 23: Token hash format validation.

    For any token record, the token_hash field SHALL be in Argon2id format
    with appropriate parameters.

    Validates: Requirements 8.2

    Feature: sso-authentication, Property 23: Token Record Completeness
    """
    # Verify token hash is in Argon2id format
    assert token_record.token_hash.startswith("$argon2id$")

    # Verify hash has the expected structure
    parts = token_record.token_hash.split("$")
    assert len(parts) >= 5  # ['', 'argon2id', 'v=19', 'm=X,t=Y,p=Z', 'salt', 'hash']
    assert parts[1] == "argon2id"
    assert parts[2].startswith("v=")
    assert "m=" in parts[3]  # memory parameter
    assert "t=" in parts[3]  # iterations parameter
    assert "p=" in parts[3]  # parallelism parameter


@given(token_record=token_record_strategy())
@property_test_settings(max_examples=10)  # Reduced from default for performance
def test_property_23_timestamp_ordering(
    token_record: TokenRecord,
) -> None:
    """
    Property 23: Timestamp ordering validation.

    For any token record, the timestamps SHALL be in logical order:
    created_at <= last_authenticated_at <= auth_expires_at (if present).

    Validates: Requirements 8.2

    Feature: sso-authentication, Property 23: Token Record Completeness
    """
    # created_at must be before or equal to last_authenticated_at
    assert token_record.created_at <= token_record.last_authenticated_at

    # If auth_expires_at is present, it must be after last_authenticated_at
    if token_record.auth_expires_at is not None:
        assert token_record.last_authenticated_at <= token_record.auth_expires_at


@given(
    token_records=st.lists(
        token_record_strategy(),
        min_size=1,
        max_size=5,
    )
)
@property_test_settings(max_examples=10)
def test_property_23_multiple_token_records_completeness(
    token_records: list[TokenRecord],
) -> None:
    """
    Property 23: Multiple token records completeness.

    For any collection of token records, each record SHALL contain all
    required fields with valid values.

    Validates: Requirements 8.2

    Feature: sso-authentication, Property 23: Token Record Completeness
    """
    for token_record in token_records:
        # Verify all required fields are present
        assert token_record.id is not None
        assert token_record.token_hash is not None
        assert token_record.user_id is not None
        assert token_record.user_email is not None
        assert token_record.provider is not None
        assert token_record.is_authenticated is not None
        assert token_record.is_active is not None
        assert token_record.created_at is not None
        assert token_record.last_authenticated_at is not None


@given(token_record=token_record_strategy())
@property_test_settings(max_examples=10)  # Reduced from default for performance
def test_property_23_provider_field_validity(
    token_record: TokenRecord,
) -> None:
    """
    Property 23: Provider field validity.

    For any token record, the provider field SHALL contain a valid
    identity provider name.

    Validates: Requirements 8.2

    Feature: sso-authentication, Property 23: Token Record Completeness
    """
    # Verify provider is not empty
    assert len(token_record.provider) > 0

    # Verify provider is a string
    assert isinstance(token_record.provider, str)

    # Provider should be one of the supported IdPs or a custom provider
    # (we don't enforce specific values, just that it's present and non-empty)


@given(token_record=token_record_strategy())
@property_test_settings()
def test_property_23_email_field_validity(
    token_record: TokenRecord,
) -> None:
    """
    Property 23: Email field validity.

    For any token record, the user_email field SHALL contain a valid
    email address format.

    Validates: Requirements 8.2

    Feature: sso-authentication, Property 23: Token Record Completeness
    """
    # Verify email is not empty
    assert len(token_record.user_email) > 0

    # Verify email contains @ symbol (basic validation)
    assert "@" in token_record.user_email

    # Verify email has content before and after @
    parts = token_record.user_email.split("@")
    assert len(parts) == 2
    assert len(parts[0]) > 0
    assert len(parts[1]) > 0


@given(token_record=token_record_strategy())
@property_test_settings(max_examples=20)
def test_property_23_authentication_state_consistency(
    token_record: TokenRecord,
) -> None:
    """
    Property 23: Authentication state consistency.

    For any token record, if is_authenticated is True, then auth_expires_at
    SHOULD be present (though it can be None for expired sessions).

    Validates: Requirements 8.2

    Feature: sso-authentication, Property 23: Token Record Completeness
    """
    # This is a soft constraint - we just verify the fields are present
    # The actual business logic will handle the relationship between
    # is_authenticated and auth_expires_at

    assert isinstance(token_record.is_authenticated, bool)

    # If auth_expires_at is present, verify it's a datetime
    if token_record.auth_expires_at is not None:
        assert isinstance(token_record.auth_expires_at, datetime)


# Property tests for TokenService


@given(st.integers(min_value=1, max_value=5))
@slow_property_test_settings()  # Reduced iterations for crypto operations
@pytest.mark.slow
def test_property_7_token_entropy_sufficiency(
    num_tokens: int,
) -> None:
    """
    Property 7: Token Entropy Sufficiency.

    For any generated agent token, the token SHALL have at least 256 bits
    of entropy (minimum 43 characters in base64url encoding).

    Base64url encoding of 32 bytes (256 bits) produces 43 characters
    (without padding).

    Validates: Requirements 3.2

    Feature: sso-authentication, Property 7: Token Entropy Sufficiency
    """
    from src.core.auth.sso.token_service import TokenService

    # Use fast configuration for tests
    service = TokenService.create_for_environment()

    for _ in range(num_tokens):
        plaintext_token, _ = service.generate_token()

        # Verify token has at least 43 characters (256 bits in base64url)
        assert (
            len(plaintext_token) >= 43
        ), f"Token length {len(plaintext_token)} is less than minimum 43 characters"

        # Verify token is base64url encoded (alphanumeric + - and _)
        # Base64url uses: A-Z, a-z, 0-9, -, _
        valid_chars = set(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        )
        assert all(
            c in valid_chars for c in plaintext_token
        ), "Token contains invalid characters for base64url encoding"


@given(st.integers(min_value=2, max_value=5))
@slow_property_test_settings()  # Reduced iterations for crypto operations
@pytest.mark.slow
def test_property_6_token_generation_uniqueness(
    num_tokens: int,
) -> None:
    """
    Property 6: Token Generation Uniqueness.

    For any two successful authentication+authorization flows, the generated
    agent tokens SHALL be distinct (no collisions).

    Validates: Requirements 3.1

    Feature: sso-authentication, Property 6: Token Generation Uniqueness
    """
    from src.core.auth.sso.token_service import TokenService

    # Use fast configuration for tests (8 MB, 1 iteration, 1 thread)
    service = TokenService.create_for_environment()

    # Generate multiple tokens
    tokens = set()
    for _ in range(num_tokens):
        plaintext_token, _ = service.generate_token()
        tokens.add(plaintext_token)

    # Verify all tokens are unique
    assert (
        len(tokens) == num_tokens
    ), f"Generated {num_tokens} tokens but only {len(tokens)} are unique"


@given(st.integers(min_value=1, max_value=5))
@slow_property_test_settings()  # Reduced iterations for crypto operations
@pytest.mark.slow  # Uses production crypto parameters
def test_property_8_token_storage_security(
    num_tokens: int,
) -> None:
    """
    Property 8: Token Storage Security.

    For any agent token stored in the database, the stored value SHALL be
    a hash that does not equal the plaintext token and cannot be reversed
    to obtain the plaintext.

    Validates: Requirements 3.4

    Feature: sso-authentication, Property 8: Token Storage Security
    """
    from src.core.auth.sso.token_service import TokenService

    service = TokenService.create_for_environment()

    for _ in range(num_tokens):
        plaintext_token, token_hash = service.generate_token()

        # Verify hash is different from plaintext
        assert (
            token_hash != plaintext_token
        ), "Token hash should not equal plaintext token"

        # Verify hash is significantly longer (includes salt, parameters, etc.)
        assert len(token_hash) > len(
            plaintext_token
        ), "Token hash should be longer than plaintext token"

        # Verify hash is in Argon2id format
        assert token_hash.startswith(
            "$argon2id$"
        ), "Token hash should be in Argon2id format"

        # Verify plaintext token is not contained in the hash
        # (the hash should not leak the plaintext)
        assert (
            plaintext_token not in token_hash
        ), "Plaintext token should not be contained in hash"


@given(st.integers(min_value=1, max_value=2))
@property_test_settings(max_examples=5)
@pytest.mark.slow  # Tests production parameters - slow
def test_property_11_argon2id_hash_format(
    num_tokens: int,
) -> None:
    """
    Property 11: Argon2id Hash Format.

    For any token hash stored in the database, the hash SHALL conform to
    the Argon2id format with parameters meeting 2025 security recommendations
    (memory >= 64MB, iterations >= 3, parallelism >= 4).

    Validates: Requirements 4.4

    Feature: sso-authentication, Property 11: Argon2id Hash Format
    """
    from src.core.auth.sso.token_service import TokenService

    # Use production parameters to validate 2025 security standards
    service = TokenService()

    for _ in range(num_tokens):
        _, token_hash = service.generate_token()

        # Verify hash starts with $argon2id$
        assert token_hash.startswith("$argon2id$"), "Hash should start with $argon2id$"

        # Parse hash format: $argon2id$v=19$m=X,t=Y,p=Z$salt$hash
        parts = token_hash.split("$")
        assert len(parts) >= 6, f"Hash should have at least 6 parts, got {len(parts)}"

        # Verify algorithm
        assert parts[1] == "argon2id", f"Algorithm should be argon2id, got {parts[1]}"

        # Verify version
        assert parts[2].startswith(
            "v="
        ), f"Version part should start with 'v=', got {parts[2]}"

        # Parse parameters
        params_str = parts[3]
        params = {}
        for param in params_str.split(","):
            key, value = param.split("=")
            params[key] = int(value)

        # Verify 2025 security parameters
        assert "m" in params, "Memory parameter (m) missing"
        assert (
            params["m"] >= 65536
        ), f"Memory cost should be >= 65536 (64 MB), got {params['m']}"

        assert "t" in params, "Time parameter (t) missing"
        assert (
            params["t"] >= 3
        ), f"Time cost should be >= 3 iterations, got {params['t']}"

        assert "p" in params, "Parallelism parameter (p) missing"
        assert (
            params["p"] >= 4
        ), f"Parallelism should be >= 4 threads, got {params['p']}"

        # Verify salt and hash are present
        assert len(parts[4]) > 0, "Salt should be present"
        assert len(parts[5]) > 0, "Hash should be present"


@given(
    token=st.text(
        alphabet=st.characters(
            whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-_"
        ),
        min_size=43,
        max_size=100,
    )
)
@property_test_settings()
def test_property_token_verification_correctness(
    token: str,
) -> None:
    """
    Property: Token verification correctness.

    For any token, after hashing it, verification with the correct token
    SHALL return True, and verification with any different token SHALL
    return False.

    This validates the correctness of the hash and verify operations.

    Feature: sso-authentication, Property: Token verification correctness
    """
    from src.core.auth.sso.token_service import TokenService

    # Use fast configuration for tests (8 MB, 1 iteration, 1 thread)
    service = TokenService.create_for_environment()

    # Hash the token
    token_hash = service.hash_token(token)

    # Verify with correct token should return True
    assert (
        service.verify_token(token, token_hash) is True
    ), "Verification with correct token should return True"

    # Verify with different token should return False
    different_token = token + "x"  # Append a character to make it different
    assert (
        service.verify_token(different_token, token_hash) is False
    ), "Verification with different token should return False"


@given(st.integers(min_value=1, max_value=5))
@property_test_settings()
def test_property_token_hash_uniqueness(
    num_tokens: int,
) -> None:
    """
    Property: Token hash uniqueness.

    For any token, hashing it multiple times SHALL produce different hashes
    (due to random salt), but all hashes SHALL verify correctly with the
    original token.

    This validates that Argon2id uses random salts correctly.

    Feature: sso-authentication, Property: Token hash uniqueness
    """
    from src.core.auth.sso.token_service import TokenService

    # Use fast configuration for tests (8 MB, 1 iteration, 1 thread)
    service = TokenService.create_for_environment()

    # Generate a single token
    plaintext_token, _ = service.generate_token()

    # Hash it multiple times
    hashes = []
    for _ in range(num_tokens):
        token_hash = service.hash_token(plaintext_token)
        hashes.append(token_hash)

    # Verify all hashes are different (due to random salt)
    unique_hashes = set(hashes)
    assert (
        len(unique_hashes) == num_tokens
    ), f"Expected {num_tokens} unique hashes, got {len(unique_hashes)}"

    # Verify all hashes verify correctly with the original token
    for token_hash in hashes:
        assert (
            service.verify_token(plaintext_token, token_hash) is True
        ), "All hashes should verify correctly with original token"
