"""Tests for backend retry-after handling."""

from unittest.mock import Mock

import pytest
from src.connectors.base import LLMBackend
from src.core.config.app_config import AppConfig

from tests.utils.fake_clock import FakeClockContext


class MockBackend(LLMBackend):
    """Mock backend for testing."""

    backend_type = "mock"

    async def chat_completions(
        self, request_data, processed_messages, effective_model, identity=None, **kwargs
    ):
        """Mock chat completions."""
        return Mock()

    async def initialize(self, **kwargs):
        """Mock initialize."""

    def get_available_models(self) -> list[str]:
        """Return empty list for mock."""
        return []


@pytest.fixture
def mock_backend():
    """Create a mock backend instance."""
    config = AppConfig()
    return MockBackend(config)


@pytest.mark.asyncio
async def test_backend_retry_after_set_and_get(mock_backend):
    """Test setting and getting retry-after values."""
    async with FakeClockContext():
        # Initially no retry-after
        assert mock_backend.get_retry_after_remaining() is None
        assert not mock_backend.is_rate_limited()

        # Set retry-after for 5 seconds
        mock_backend.set_retry_after(5.0)

        # Should be rate limited
        assert mock_backend.is_rate_limited()

        # Should have remaining time close to 5 seconds
        remaining = mock_backend.get_retry_after_remaining()
        assert remaining is not None
        assert 4.5 <= remaining <= 5.0


@pytest.mark.asyncio
async def test_backend_retry_after_expiration(mock_backend):
    """Test that retry-after expires after the specified time."""
    async with FakeClockContext() as clock:
        # Set retry-after for 0.1 seconds
        mock_backend.set_retry_after(0.1)

        # Should be rate limited
        assert mock_backend.is_rate_limited()

        # Advance past expiration
        clock.advance(0.15)

        # Should no longer be rate limited
        assert not mock_backend.is_rate_limited()
        assert mock_backend.get_retry_after_remaining() is None


@pytest.mark.asyncio
async def test_backend_retry_after_zero_or_negative(mock_backend):
    """Test that zero or negative retry-after is handled correctly."""
    async with FakeClockContext():
        # Set retry-after for 0 seconds
        mock_backend.set_retry_after(0.0)

        # Should immediately expire
        assert not mock_backend.is_rate_limited()
        assert mock_backend.get_retry_after_remaining() is None


@pytest.mark.asyncio
async def test_backend_retry_after_update(mock_backend):
    """Test updating retry-after value."""
    async with FakeClockContext():
        # Set initial retry-after
        mock_backend.set_retry_after(10.0)
        first_remaining = mock_backend.get_retry_after_remaining()

        # Update to shorter time
        mock_backend.set_retry_after(2.0)
        second_remaining = mock_backend.get_retry_after_remaining()

        # Second should be less than first
        assert second_remaining is not None
        assert first_remaining is not None
        assert second_remaining < first_remaining


@pytest.mark.asyncio
async def test_backend_retry_after_prevents_spam(mock_backend):
    """Test that retry-after prevents repeated calls to rate-limited backend."""
    async with FakeClockContext():
        # Set retry-after for 10 seconds
        mock_backend.set_retry_after(10.0)

        # Verify backend is rate limited
        assert mock_backend.is_rate_limited()

        # Simulate multiple attempts - all should see the rate limit
        for _ in range(5):
            assert mock_backend.is_rate_limited()
            remaining = mock_backend.get_retry_after_remaining()
            assert remaining is not None
            assert remaining > 0

        # The retry-after should still be active
        assert mock_backend.is_rate_limited()
