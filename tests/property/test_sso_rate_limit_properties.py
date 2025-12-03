"""Property-based tests for SSO rate limiting.

Feature: sso-authentication
Property: 17
Validates: Requirements 6.6
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from src.core.auth.sso.database import DatabaseManager
from src.core.auth.sso.rate_limit_service import RateLimitService
from tests.utils.hypothesis_config import property_test_settings


async def create_temp_database():
    """Create a temporary database for testing."""
    # Create temporary directory
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_sso.db")

    # Initialize database
    db_manager = DatabaseManager(db_path)
    await db_manager.initialize_schema()

    return db_path, temp_dir


async def cleanup_temp_database(db_path: str, temp_dir: str):
    """Cleanup temporary database."""
    try:
        Path(db_path).unlink(missing_ok=True)
        Path(temp_dir).rmdir()
    except Exception:
        pass


@given(
    identifier=st.text(min_size=1, max_size=100),
    num_failures=st.integers(min_value=1, max_value=10),
)
@property_test_settings()
@pytest.mark.asyncio
async def test_property_17_exponential_backoff_enforcement(
    identifier: str,
    num_failures: int,
) -> None:
    """
    Property 17: Exponential Backoff Enforcement.

    For any sequence of N failed confirmation code attempts, the required wait
    time before the next SSO attempt SHALL increase exponentially (e.g., 2^N
    seconds, capped at a maximum).

    Validates: Requirements 6.6

    Feature: sso-authentication, Property 17: Exponential Backoff Enforcement
    """
    # Create temporary database for this test
    temp_database, temp_dir = await create_temp_database()

    try:
        service = RateLimitService(temp_database)

        # Record N failed attempts
        for _ in range(num_failures):
            await service.record_failed_attempt(identifier)

        # Check rate limit status
        result = await service.check_rate_limit(identifier)

        # Should be blocked after failed attempts
        assert result.allowed is False
        assert result.retry_after > 0

        # Verify exponential backoff: 2^N seconds (capped at MAX_BACKOFF_SECONDS)
        expected_backoff = min(
            service.BASE_BACKOFF_SECONDS**num_failures,
            service.MAX_BACKOFF_SECONDS,
        )

        # Allow some tolerance for timing and database operations
        # The retry_after should be close to expected_backoff
        assert result.retry_after <= expected_backoff
        assert result.retry_after >= expected_backoff - 2  # Allow 2 second tolerance

    finally:
        await cleanup_temp_database(temp_database, temp_dir)


@given(
    identifier=st.text(min_size=1, max_size=100),
    num_failures=st.integers(min_value=1, max_value=15),
)
@property_test_settings()
@pytest.mark.asyncio
async def test_property_17_backoff_cap_enforcement(
    identifier: str,
    num_failures: int,
) -> None:
    """
    Property 17: Backoff cap enforcement.

    For any number of failed attempts, the backoff time SHALL never exceed
    MAX_BACKOFF_SECONDS.

    Validates: Requirements 6.6

    Feature: sso-authentication, Property 17: Exponential Backoff Enforcement
    """
    # Create temporary database for this test
    temp_database, temp_dir = await create_temp_database()

    try:
        service = RateLimitService(temp_database)

        # Record N failed attempts
        for _ in range(num_failures):
            await service.record_failed_attempt(identifier)

        # Check rate limit status
        result = await service.check_rate_limit(identifier)

        # Backoff should never exceed maximum
        assert result.retry_after <= service.MAX_BACKOFF_SECONDS

    finally:
        await cleanup_temp_database(temp_database, temp_dir)


@given(
    identifier=st.text(min_size=1, max_size=100),
    num_failures=st.integers(min_value=2, max_value=8),
)
@property_test_settings()
@pytest.mark.asyncio
async def test_property_17_backoff_increases_monotonically(
    identifier: str,
    num_failures: int,
) -> None:
    """
    Property 17: Backoff increases monotonically.

    For any sequence of failed attempts, each additional failure SHALL result
    in a backoff time that is greater than or equal to the previous backoff
    (until the cap is reached).

    Validates: Requirements 6.6

    Feature: sso-authentication, Property 17: Exponential Backoff Enforcement
    """
    # Create temporary database for this test
    temp_database, temp_dir = await create_temp_database()

    try:
        service = RateLimitService(temp_database)

        previous_retry_after = 0

        # Record failures one at a time and verify backoff increases
        for i in range(1, num_failures + 1):
            await service.record_failed_attempt(identifier)

            result = await service.check_rate_limit(identifier)

            # Backoff should increase or stay at cap
            assert result.retry_after >= previous_retry_after

            # If we haven't hit the cap, backoff should strictly increase
            if result.retry_after < service.MAX_BACKOFF_SECONDS:
                if i > 1:  # After first failure
                    assert result.retry_after > previous_retry_after

            previous_retry_after = result.retry_after

    finally:
        await cleanup_temp_database(temp_database, temp_dir)


@given(
    identifier=st.text(min_size=1, max_size=100),
    num_failures=st.integers(min_value=1, max_value=5),
)
@property_test_settings()
@pytest.mark.asyncio
async def test_property_17_reset_clears_backoff(
    identifier: str,
    num_failures: int,
) -> None:
    """
    Property 17: Reset clears backoff.

    For any identifier with failed attempts, calling reset_rate_limit SHALL
    clear the backoff and allow immediate retry.

    Validates: Requirements 6.6

    Feature: sso-authentication, Property 17: Exponential Backoff Enforcement
    """
    # Create temporary database for this test
    temp_database, temp_dir = await create_temp_database()

    try:
        service = RateLimitService(temp_database)

        # Record N failed attempts
        for _ in range(num_failures):
            await service.record_failed_attempt(identifier)

        # Verify blocked
        result_before = await service.check_rate_limit(identifier)
        assert result_before.allowed is False

        # Reset rate limit
        await service.reset_rate_limit(identifier)

        # Verify no longer blocked
        result_after = await service.check_rate_limit(identifier)
        assert result_after.allowed is True
        assert result_after.retry_after == 0

    finally:
        await cleanup_temp_database(temp_database, temp_dir)


@given(
    identifiers=st.lists(
        st.text(min_size=1, max_size=100),
        min_size=2,
        max_size=5,
        unique=True,
    ),
    failures_per_identifier=st.lists(
        st.integers(min_value=1, max_value=5),
        min_size=2,
        max_size=5,
    ),
)
@property_test_settings()
@pytest.mark.asyncio
async def test_property_17_independent_identifier_backoff(
    identifiers: list[str],
    failures_per_identifier: list[int],
) -> None:
    """
    Property 17: Independent identifier backoff.

    For any set of different identifiers, the backoff for each identifier SHALL
    be independent and not affect other identifiers.

    Validates: Requirements 6.6

    Feature: sso-authentication, Property 17: Exponential Backoff Enforcement
    """
    # Ensure we have matching lists
    if len(failures_per_identifier) < len(identifiers):
        failures_per_identifier = failures_per_identifier * (
            len(identifiers) // len(failures_per_identifier) + 1
        )
    failures_per_identifier = failures_per_identifier[: len(identifiers)]

    # Create temporary database for this test
    temp_database, temp_dir = await create_temp_database()

    try:
        service = RateLimitService(temp_database)

        # Record different numbers of failures for each identifier
        for identifier, num_failures in zip(identifiers, failures_per_identifier):
            for _ in range(num_failures):
                await service.record_failed_attempt(identifier)

        # Verify each identifier has independent backoff
        for identifier, num_failures in zip(identifiers, failures_per_identifier):
            result = await service.check_rate_limit(identifier)

            # Calculate expected backoff for this identifier
            expected_backoff = min(
                service.BASE_BACKOFF_SECONDS**num_failures,
                service.MAX_BACKOFF_SECONDS,
            )

            # Verify backoff matches expected for this identifier
            assert result.retry_after <= expected_backoff
            assert result.retry_after >= expected_backoff - 2

    finally:
        await cleanup_temp_database(temp_database, temp_dir)


@given(identifier=st.text(min_size=1, max_size=100))
@property_test_settings()
@pytest.mark.asyncio
async def test_property_17_no_backoff_on_first_check(
    identifier: str,
) -> None:
    """
    Property 17: No backoff on first check.

    For any identifier with no previous failed attempts, check_rate_limit SHALL
    return allowed=True with retry_after=0.

    Validates: Requirements 6.6

    Feature: sso-authentication, Property 17: Exponential Backoff Enforcement
    """
    # Create temporary database for this test
    temp_database, temp_dir = await create_temp_database()

    try:
        service = RateLimitService(temp_database)

        # Check rate limit for new identifier
        result = await service.check_rate_limit(identifier)

        # Should be allowed with no backoff
        assert result.allowed is True
        assert result.retry_after == 0

    finally:
        await cleanup_temp_database(temp_database, temp_dir)


@given(
    identifier=st.text(min_size=1, max_size=100),
    num_failures=st.integers(min_value=1, max_value=5),
)
@property_test_settings()
@pytest.mark.asyncio
async def test_property_17_backoff_expires_over_time(
    identifier: str,
    num_failures: int,
) -> None:
    """
    Property 17: Backoff expires over time.

    For any identifier with failed attempts, after the backoff period expires,
    check_rate_limit SHALL return allowed=True.

    Note: This test verifies the logic but doesn't wait for actual time to pass.
    It checks that the blocked_until timestamp is correctly set in the future.

    Validates: Requirements 6.6

    Feature: sso-authentication, Property 17: Exponential Backoff Enforcement
    """
    # Create temporary database for this test
    temp_database, temp_dir = await create_temp_database()

    try:
        service = RateLimitService(temp_database)

        # Record N failed attempts
        for _ in range(num_failures):
            await service.record_failed_attempt(identifier)

        # Check rate limit status
        result = await service.check_rate_limit(identifier)

        # Should be blocked
        assert result.allowed is False
        assert result.retry_after > 0

        # Verify the blocked_until timestamp is in the future
        import aiosqlite

        async with aiosqlite.connect(temp_database) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT blocked_until FROM rate_limits WHERE identifier = ?",
                (identifier,),
            )
            row = await cursor.fetchone()

            assert row is not None
            blocked_until = datetime.fromisoformat(row["blocked_until"])

            # blocked_until should be in the future
            now = datetime.utcnow()
            assert blocked_until > now

            # The time difference should match retry_after (within tolerance)
            time_diff = (blocked_until - now).total_seconds()
            assert abs(time_diff - result.retry_after) < 2

    finally:
        await cleanup_temp_database(temp_database, temp_dir)
