"""
Property-based tests for SSO authorization service.

These tests verify correctness properties for confirmation code generation,
verification, and authorization flows using Hypothesis.
"""

import os
import tempfile
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from src.core.auth.sso.authorization_service import (
    AuthorizationMode,
    AuthorizationService,
)
from src.core.auth.sso.config import AuthorizationConfig
from tests.utils.fake_clock import FakeClockContext
from src.core.auth.sso.database import DatabaseManager
from src.core.auth.sso.rate_limit_service import RateLimitService


@asynccontextmanager
async def temp_database_context():
    """Context manager for creating a temporary database."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
        db_path = f.name

    try:
        # Initialize database schema
        db_manager = DatabaseManager(db_path)
        await db_manager.initialize_schema()

        yield db_path
    finally:
        # Cleanup
        with suppress(Exception):
            os.unlink(db_path)


async def create_authorization_service(
    database_path: str,
    mode: AuthorizationMode = AuthorizationMode.SINGLE_USER,
    confirmation_code_expiry_minutes: int = 10,
    max_confirmation_attempts: int = 3,
) -> AuthorizationService:
    """Helper to create an AuthorizationService with proper dependencies."""
    db_manager = DatabaseManager(database_path)
    rate_limit_service = RateLimitService(db_manager)

    config = AuthorizationConfig(
        mode="single_user" if mode == AuthorizationMode.SINGLE_USER else "enterprise",
        api_url=None,
        api_timeout=10,
        confirmation_code_expiry_minutes=confirmation_code_expiry_minutes,
        max_confirmation_attempts=max_confirmation_attempts,
    )

    return AuthorizationService(
        mode=mode,
        config=config,
        database_manager=db_manager,
        rate_limit_service=rate_limit_service,
    )


# Feature: sso-authentication, Property 15: Confirmation Code Attempt Decrement
@pytest.mark.asyncio
@settings(
    max_examples=15,  # Reduced from 30 for performance (still provides good coverage)
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    # Generate a sequence of incorrect codes (not matching the actual code)
    incorrect_attempts=st.integers(min_value=1, max_value=5)
)
async def test_property_15_confirmation_code_attempt_decrement(incorrect_attempts):
    """
    Property 15: Confirmation Code Attempt Decrement

    For any incorrect confirmation code entry in single-user mode,
    the remaining attempts counter SHALL decrease by exactly 1.

    Validates: Requirements 6.3
    """
    async with temp_database_context() as temp_database:
        # Create service
        service = await create_authorization_service(temp_database)

        # Create a pending authorization
        sso_state = "test_state"
        await service.create_pending_authorization(
            sso_state=sso_state,
            user_email="test@example.com",
            user_id="test_user",
            provider="google",
            client_ip="127.0.0.1",
        )

        # Track attempts
        initial_attempts = 3
        expected_attempts = initial_attempts

        # Make incorrect attempts (up to the number we want to test)
        import asyncio

        for i in range(min(incorrect_attempts, initial_attempts)):
            # Use a code that's definitely wrong
            wrong_code = "999999"

            # Use different IP for each attempt to avoid rate limiting in tests
            client_ip = f"127.0.0.{i + 1}"
            result = await service.verify_confirmation_code(
                sso_state, wrong_code, client_ip
            )

            # Verify attempt was decremented by exactly 1
            expected_attempts -= 1
            assert result.attempts_remaining == expected_attempts, (
                f"After {i + 1} incorrect attempts, expected {expected_attempts} "
                f"remaining but got {result.attempts_remaining}"
            )
            assert not result.success, "Incorrect code should not succeed"

            # If we've exhausted attempts, must_reauthenticate should be True
            if expected_attempts <= 0:
                assert (
                    result.must_reauthenticate
                ), "must_reauthenticate should be True when attempts exhausted"
                break

            # Small delay to avoid timing issues (reduced from 0.01s to 0.001s)
            async with FakeClockContext() as clock:
                sleep_task = asyncio.create_task(asyncio.sleep(0.001))
                clock.advance(0.001)
                await sleep_task


# Feature: sso-authentication, Property 16: Correct Confirmation Code Success
@pytest.mark.asyncio
@settings(
    max_examples=5,  # Reduced from 10 for performance
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    user_email=st.emails(),
    user_id=st.text(min_size=1, max_size=50),  # Reduced from 100 for performance
    provider=st.sampled_from(["google", "microsoft", "github", "linkedin"]),
)
async def test_property_16_correct_confirmation_code_success(
    user_email, user_id, provider
):
    """
    Property 16: Correct Confirmation Code Success

    For any correct confirmation code entry in single-user mode,
    the proxy SHALL generate and return a valid agent token.

    Note: This test verifies the confirmation succeeds. Token generation
    is tested separately as it's handled by a different service.

    Validates: Requirements 6.5
    """
    async with temp_database_context() as temp_database:
        # Create service
        service = await create_authorization_service(temp_database)

        # Generate a code manually so we know what it is
        correct_code = service.generate_confirmation_code()
        code_hash = service._hash_code(correct_code)

        # Manually insert pending authorization with known code
        import secrets

        import aiosqlite

        sso_state = "test_state"
        expires_at = datetime.utcnow() + timedelta(minutes=10)

        async with aiosqlite.connect(temp_database) as db:
            await db.execute(
                """
                INSERT INTO pending_authorizations (
                    id, sso_state, user_email, user_id, provider,
                    confirmation_code_hash, attempts_remaining,
                    created_at, expires_at, client_ip
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    secrets.token_hex(16),
                    sso_state,
                    user_email,
                    user_id,
                    provider,
                    code_hash,
                    3,
                    datetime.utcnow().isoformat(),
                    expires_at.isoformat(),
                    "127.0.0.1",
                ),
            )
            await db.commit()

        # Verify with correct code
        result = await service.verify_confirmation_code(
            sso_state, correct_code, "127.0.0.1"
        )

        # Verify success
        assert result.success, "Correct confirmation code should succeed"
        assert (
            not result.must_reauthenticate
        ), "Should not require re-authentication on success"


@pytest.mark.asyncio
async def test_confirmation_code_generation_format():
    """
    Test that generated confirmation codes are 6-digit strings.

    This is a basic sanity check, not a full property test.
    """
    async with temp_database_context() as temp_database:
        service = await create_authorization_service(temp_database)

        # Generate multiple codes
        codes = [service.generate_confirmation_code() for _ in range(100)]

        for code in codes:
            # Verify format
            assert len(code) == 6, f"Code {code} is not 6 digits"
            assert code.isdigit(), f"Code {code} contains non-digit characters"
            assert 0 <= int(code) <= 999999, f"Code {code} is out of range"


@pytest.mark.asyncio
async def test_confirmation_code_expiry():
    """
    Test that expired confirmation codes are rejected.
    """
    async with temp_database_context() as temp_database:
        service = await create_authorization_service(temp_database)

        # Create a pending authorization
        sso_state = "test_state"
        await service.create_pending_authorization(
            sso_state=sso_state,
            user_email="test@example.com",
            user_id="test_user",
            provider="google",
            client_ip="127.0.0.1",
        )

        # Manually expire the code by updating the database
        import aiosqlite

        async with aiosqlite.connect(temp_database) as db:
            expired_time = datetime.utcnow() - timedelta(minutes=1)
            await db.execute(
                "UPDATE pending_authorizations SET expires_at = ? WHERE sso_state = ?",
                (expired_time.isoformat(), sso_state),
            )
            await db.commit()

        # Try to verify - should fail due to expiry and require re-authentication
        result = await service.verify_confirmation_code(
            sso_state, "123456", "127.0.0.1"
        )
        assert not result.success, "Expired code should not succeed"
        assert (
            result.must_reauthenticate
        ), "Expired code should require re-authentication"


@pytest.mark.asyncio
async def test_confirmation_code_attempts_exhausted():
    """
    Test that after 3 failed attempts, must_reauthenticate is True.
    """
    async with temp_database_context() as temp_database:
        service = await create_authorization_service(temp_database)

        # Create a pending authorization
        sso_state = "test_state"
        await service.create_pending_authorization(
            sso_state=sso_state,
            user_email="test@example.com",
            user_id="test_user",
            provider="google",
            client_ip="127.0.0.1",
        )

        # Make 3 incorrect attempts
        wrong_code = "999999"
        import asyncio

        for i in range(3):
            # Use different IP for each attempt to avoid rate limiting in tests
            client_ip = f"127.0.0.{i + 1}"
            result = await service.verify_confirmation_code(
                sso_state, wrong_code, client_ip
            )
            assert not result.success

            if i < 2:
                assert not result.must_reauthenticate
            else:
                # After 3rd failure, must re-authenticate
                assert result.must_reauthenticate
                assert result.attempts_remaining == 0

            # Small delay to avoid timing issues (reduced from 0.01s to 0.001s)
            async with FakeClockContext() as clock:
                sleep_task = asyncio.create_task(asyncio.sleep(0.001))
                clock.advance(0.001)
                await sleep_task

        # Try one more time - should still require re-authentication
        result = await service.verify_confirmation_code(
            sso_state, wrong_code, "127.0.0.4"
        )
        assert not result.success
        assert result.must_reauthenticate
        assert result.attempts_remaining == 0
