"""Property-based tests for SSO rate limiting.

Feature: sso-authentication
Property: 17
Validates: Requirements 6.6
"""

from __future__ import annotations

import asyncio
import tempfile
from contextlib import contextmanager
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st
from src.core.auth.sso.database import DatabaseManager
from src.core.auth.sso.rate_limit_service import RateLimitService
from tests.utils.hypothesis_config import property_test_settings


@contextmanager
def temp_db_path():
    """Context manager for temporary database path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield str(Path(tmpdir) / "test.db")


@given(
    num_failures=st.integers(min_value=1, max_value=10),
)
@property_test_settings()
def test_property_17_exponential_backoff_enforcement(
    num_failures: int,
) -> None:
    """
    Property 17: Exponential Backoff Enforcement.

    For any sequence of N failed confirmation code attempts, the required wait
    time before the next SSO attempt SHALL increase exponentially
    (e.g., 2^N seconds, capped at a maximum).

    Validates: Requirements 6.6

    Feature: sso-authentication, Property 17: Exponential Backoff Enforcement
    """

    async def run_test():
        with temp_db_path() as db_path:
            # Setup
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize_schema()
            service = RateLimitService(db_manager)
            identifier = "test-ip-127.0.0.1"

            previous_retry_after = 0

            for i in range(num_failures):
                # Record failure
                await service.record_failed_attempt(identifier)

                # Check rate limit
                result = await service.check_rate_limit(identifier)

                # Must be blocked
                assert result.allowed is False
                assert result.retry_after > 0

                # Wait time should increase or stay same (if capped)
                # For first few failures, it should strictly increase
                if i < 8 and i > 0:  # 2^8 is 256s, well below cap
                    assert result.retry_after > previous_retry_after

                # Verify exponential growth approximately
                # Base delay is 2s.
                # Attempt 1: 2s
                # Attempt 2: 4s
                # Attempt 3: 8s
                expected_delay = min(
                    service.BASE_DELAY_SECONDS * (2**i), service.MAX_DELAY_SECONDS
                )
                # Allow some jitter/processing time difference (±1s)
                assert abs(result.retry_after - expected_delay) <= 2

                previous_retry_after = result.retry_after

            # Reset
            await service.reset_rate_limit(identifier)
            result = await service.check_rate_limit(identifier)
            assert result.allowed is True
            assert result.retry_after == 0

    asyncio.run(run_test())
