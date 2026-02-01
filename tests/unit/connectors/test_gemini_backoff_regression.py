
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.connectors.gemini_oauth_auto.connector import GeminiOAuthAutoConnector
from src.connectors.gemini_oauth_auto.models import StoredAccount
from src.core.common.exceptions import BackendError

from tests.utils.fake_clock import FakeClock, FakeClockContext


@pytest.mark.asyncio
async def test_exponential_backoff_logic():
    """Verify that StoredAccount applies exponential backoff on consecutive limits."""
    async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
        account = StoredAccount(
            account_id="test-acc",
            email="test@example.com",
            access_token="at",
            refresh_token="rt",
            scope="scope",
            expiry_date=int(clock.now() * 1000) + 3600000
        )
        
        default_wait = 30.0
        
        # First rate limit (30s * 2^0 = 30s)
        limited1 = account.mark_rate_limited(retry_after_seconds=None, default_window_seconds=default_wait)
        assert limited1.consecutive_rate_limits == 1
        # Check window (30s +/- 10% jitter)
        rate_limited_until1 = limited1.rate_limited_until
        assert rate_limited_until1 is not None
        diff1 = (rate_limited_until1 - int(clock.now() * 1000)) / 1000.0
        assert 26.0 <= diff1 <= 34.0
        
        # Second rate limit (30s * 2^1 = 60s)
        limited2 = limited1.mark_rate_limited(retry_after_seconds=None, default_window_seconds=default_wait)
        assert limited2.consecutive_rate_limits == 2
        rate_limited_until2 = limited2.rate_limited_until
        assert rate_limited_until2 is not None
        diff2 = (rate_limited_until2 - int(clock.now() * 1000)) / 1000.0
        assert 53.0 <= diff2 <= 67.0
        
        # Third rate limit (30s * 2^2 = 120s)
        limited3 = limited2.mark_rate_limited(retry_after_seconds=None, default_window_seconds=default_wait)
        assert limited3.consecutive_rate_limits == 3
        rate_limited_until3 = limited3.rate_limited_until
        assert rate_limited_until3 is not None
        diff3 = (rate_limited_until3 - int(clock.now() * 1000)) / 1000.0
        assert 107.0 <= diff3 <= 133.0

@pytest.mark.asyncio
async def test_explicit_retry_after_overrides_backoff():
    """Verify that explicit retry_after from API overrides the exponential backoff."""
    async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
        account = StoredAccount(
            account_id="test-acc",
            email="test@example.com",
            access_token="at",
            refresh_token="rt",
            scope="scope",
            expiry_date=int(clock.now() * 1000) + 3600000,
            consecutive_rate_limits=5 # Should be a very long wait normally
        )
        
        # API says 5 seconds
        limited = account.mark_rate_limited(retry_after_seconds=5.0, default_window_seconds=30.0)
        rate_limited_until = limited.rate_limited_until
        assert rate_limited_until is not None
        diff = (rate_limited_until - int(clock.now() * 1000)) / 1000.0
        # Should be exactly 5s (no jitter on explicit API values usually, but our impl adds it if we don't branch)
        # Actually models.py:220 shows wait_seconds = float(retry_after_seconds) directly
        assert 4.0 <= diff <= 6.0

@pytest.mark.asyncio
async def test_retry_after_propagation_in_connector():
    """Verify that the connector correctly extracts and passes retry_after to the selector."""
    client = AsyncMock()
    config = MagicMock()
    translation = MagicMock()
    
    connector = GeminiOAuthAutoConnector(client, config, translation)
    connector._account_selector = AsyncMock()
    
    # Simulate a 429 error with retry info in details
    error = BackendError("Rate limit", status_code=429, details={"retry_after": 45.5})
    
    await connector.record_rate_limit(retry_after_seconds=connector._extract_retry_after_seconds(error))
    
    # Verify the selector received the 45.5s
    connector._account_selector.mark_current_account_rate_limited.assert_called_with(45.5)
