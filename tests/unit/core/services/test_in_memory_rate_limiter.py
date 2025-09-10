"""
Tests for InMemoryRateLimiter.

This module tests the in-memory rate limiter implementation.
"""

import asyncio
import time
from typing import Any

import pytest
from src.core.interfaces.rate_limiter_interface import RateLimitInfo
from src.core.services.rate_limiter import (
    ConfigurableRateLimiter,
    InMemoryRateLimiter,
    create_rate_limiter,
)


class TestInMemoryRateLimiter:
    """Tests for InMemoryRateLimiter class."""

    @pytest.fixture
    def rate_limiter(self) -> InMemoryRateLimiter:
        """Create a fresh InMemoryRateLimiter for each test."""
        return InMemoryRateLimiter(default_limit=10, default_time_window=60)

    def test_initialization(self, rate_limiter: InMemoryRateLimiter) -> None:
        """Test rate limiter initialization."""
        assert rate_limiter._usage == {}
        assert rate_limiter._limits == {}
        assert rate_limiter._default_limit == 10
        assert rate_limiter._default_time_window == 60

    def test_initialization_defaults(self) -> None:
        """Test rate limiter initialization with defaults."""
        limiter = InMemoryRateLimiter()
        assert limiter._default_limit == 60
        assert limiter._default_time_window == 60

    @pytest.mark.asyncio
    async def test_check_limit_empty_key(
        self, rate_limiter: InMemoryRateLimiter
    ) -> None:
        """Test check_limit for a key with no usage."""
        info = await rate_limiter.check_limit("test-key")

        assert isinstance(info, RateLimitInfo)
        assert info.is_limited is False
        assert info.remaining == 10  # default limit
        assert info.reset_at is None
        assert info.limit == 10
        assert info.time_window == 60

    @pytest.mark.asyncio
    async def test_check_limit_with_usage(
        self, rate_limiter: InMemoryRateLimiter
    ) -> None:
        """Test check_limit after recording usage."""
        key = "test-key"

        # Record some usage
        await rate_limiter.record_usage(key, cost=3)

        info = await rate_limiter.check_limit(key)

        assert info.is_limited is False
        assert info.remaining == 7  # 10 - 3
        assert info.limit == 10
        assert info.time_window == 60

    @pytest.mark.asyncio
    async def test_check_limit_at_limit(
        self, rate_limiter: InMemoryRateLimiter
    ) -> None:
        """Test check_limit when at the limit."""
        key = "test-key"

        # Record usage up to the limit
        await rate_limiter.record_usage(key, cost=10)

        info = await rate_limiter.check_limit(key)

        assert info.is_limited is True  # Should be limited
        assert info.remaining == 0
        assert info.reset_at is not None  # Should have reset time
        assert info.limit == 10

    @pytest.mark.asyncio
    async def test_check_limit_over_limit(
        self, rate_limiter: InMemoryRateLimiter
    ) -> None:
        """Test check_limit when over the limit."""
        key = "test-key"

        # Record usage over the limit
        await rate_limiter.record_usage(key, cost=15)

        info = await rate_limiter.check_limit(key)

        assert info.is_limited is True
        assert info.remaining == 0  # Can't go negative
        assert info.reset_at is not None
        assert info.limit == 10

    @pytest.mark.asyncio
    async def test_record_usage_single(self, rate_limiter: InMemoryRateLimiter) -> None:
        """Test recording single usage."""
        key = "test-key"

        await rate_limiter.record_usage(key)

        # Check internal state
        assert key in rate_limiter._usage
        assert len(rate_limiter._usage[key]) == 1

    @pytest.mark.asyncio
    async def test_record_usage_multiple(
        self, rate_limiter: InMemoryRateLimiter
    ) -> None:
        """Test recording multiple usage."""
        key = "test-key"

        await rate_limiter.record_usage(key, cost=5)

        assert len(rate_limiter._usage[key]) == 5

    @pytest.mark.asyncio
    async def test_record_usage_zero_cost(
        self, rate_limiter: InMemoryRateLimiter
    ) -> None:
        """Test recording usage with zero cost."""
        key = "test-key"

        await rate_limiter.record_usage(key, cost=0)

        # Should not add any timestamps
        assert key not in rate_limiter._usage or len(rate_limiter._usage[key]) == 0

    @pytest.mark.asyncio
    async def test_reset_key(self, rate_limiter: InMemoryRateLimiter) -> None:
        """Test resetting a key."""
        key = "test-key"

        # Add some usage
        await rate_limiter.record_usage(key, cost=5)
        assert len(rate_limiter._usage[key]) == 5

        # Reset the key
        await rate_limiter.reset(key)

        # Should have no usage
        assert key not in rate_limiter._usage or len(rate_limiter._usage[key]) == 0

    @pytest.mark.asyncio
    async def test_reset_nonexistent_key(
        self, rate_limiter: InMemoryRateLimiter
    ) -> None:
        """Test resetting a nonexistent key."""
        key = "nonexistent"

        # Should not raise an error
        await rate_limiter.reset(key)

        assert key not in rate_limiter._usage

    @pytest.mark.asyncio
    async def test_set_limit_custom(self, rate_limiter: InMemoryRateLimiter) -> None:
        """Test setting custom limits."""
        key = "test-key"

        await rate_limiter.set_limit(key, limit=100, time_window=120)

        # Check internal state
        assert key in rate_limiter._limits
        assert rate_limiter._limits[key] == (100, 120)

    @pytest.mark.asyncio
    async def test_set_limit_overwrites(
        self, rate_limiter: InMemoryRateLimiter
    ) -> None:
        """Test that set_limit overwrites existing limits."""
        key = "test-key"

        # Set initial limits
        await rate_limiter.set_limit(key, limit=50, time_window=60)
        assert rate_limiter._limits[key] == (50, 60)

        # Overwrite with new limits
        await rate_limiter.set_limit(key, limit=200, time_window=300)
        assert rate_limiter._limits[key] == (200, 300)

    @pytest.mark.asyncio
    async def test_custom_limits_applied(
        self, rate_limiter: InMemoryRateLimiter
    ) -> None:
        """Test that custom limits are applied in check_limit."""
        key = "test-key"

        # Set custom limits
        await rate_limiter.set_limit(key, limit=5, time_window=30)

        # Record usage up to custom limit
        await rate_limiter.record_usage(key, cost=5)

        info = await rate_limiter.check_limit(key)

        assert info.is_limited is True
        assert info.limit == 5
        assert info.time_window == 30

    @pytest.mark.asyncio
    async def test_time_window_expiration(
        self, rate_limiter: InMemoryRateLimiter
    ) -> None:
        """Test that old timestamps are expired."""
        key = "test-key"

        # Record some usage
        await rate_limiter.record_usage(key, cost=5)
        assert len(rate_limiter._usage[key]) == 5

        # Manually add an old timestamp (beyond time window)
        old_time = time.time() - 120  # 2 minutes ago
        rate_limiter._usage[key].append(old_time)

        # Check limit - should clean up expired timestamps
        info = await rate_limiter.check_limit(key)

        # Should have only the recent timestamps
        assert len(rate_limiter._usage[key]) == 5
        assert info.remaining == 5  # 10 - 5

    @pytest.mark.asyncio
    async def test_reset_at_calculation(
        self, rate_limiter: InMemoryRateLimiter
    ) -> None:
        """Test reset_at time calculation."""
        key = "test-key"

        # Record usage up to limit
        await rate_limiter.record_usage(key, cost=10)

        # Get the timestamps
        timestamps = rate_limiter._usage[key]

        info = await rate_limiter.check_limit(key)

        assert info.is_limited is True
        assert info.reset_at is not None

        # Reset time should be the earliest timestamp + time window
        expected_reset = timestamps[0] + 60  # earliest + time window
        assert (
            abs(info.reset_at - expected_reset) < 0.1
        )  # Allow small timing differences

    @pytest.mark.asyncio
    async def test_multiple_keys_isolation(
        self, rate_limiter: InMemoryRateLimiter
    ) -> None:
        """Test that different keys are isolated."""
        key1, key2 = "key1", "key2"

        # Record usage for key1
        await rate_limiter.record_usage(key1, cost=5)

        # Check both keys
        info1 = await rate_limiter.check_limit(key1)
        info2 = await rate_limiter.check_limit(key2)

        assert info1.remaining == 5  # 10 - 5
        assert info2.remaining == 10  # default

        # Reset key1
        await rate_limiter.reset(key1)

        # Check again
        info1_after = await rate_limiter.check_limit(key1)
        info2_after = await rate_limiter.check_limit(key2)

        assert info1_after.remaining == 10  # reset
        assert info2_after.remaining == 10  # unchanged

    @pytest.mark.asyncio
    async def test_concurrent_access(self, rate_limiter: InMemoryRateLimiter) -> None:
        """Test concurrent access to the rate limiter."""
        key = "test-key"

        async def record_and_check():
            await rate_limiter.record_usage(key)
            info = await rate_limiter.check_limit(key)
            return info

        # Run multiple concurrent operations
        tasks = [record_and_check() for _ in range(5)]
        results = await asyncio.gather(*tasks)

        # Each should have different remaining counts
        remaining_values = [info.remaining for info in results]
        assert len(set(remaining_values)) == 5  # All different

    @pytest.mark.asyncio
    async def test_edge_case_zero_limits(self) -> None:
        """Test with zero default limits."""
        limiter = InMemoryRateLimiter(default_limit=0, default_time_window=60)

        info = await limiter.check_limit("test-key")

        assert info.is_limited is True  # Always limited with 0 limit
        assert info.remaining == 0
        assert info.limit == 0

    @pytest.mark.asyncio
    async def test_edge_case_large_cost(
        self, rate_limiter: InMemoryRateLimiter
    ) -> None:
        """Test recording very large cost."""
        key = "test-key"

        await rate_limiter.record_usage(key, cost=1000)

        info = await rate_limiter.check_limit(key)

        assert info.is_limited is True
        assert info.remaining == 0
        assert len(rate_limiter._usage[key]) == 1000

    @pytest.mark.asyncio
    async def test_get_limits_helper(self, rate_limiter: InMemoryRateLimiter) -> None:
        """Test the _get_limits helper method."""
        key = "test-key"

        # Test default limits
        limits = rate_limiter._get_limits(key)
        assert limits == (10, 60)

        # Set custom limits
        await rate_limiter.set_limit(key, limit=20, time_window=120)
        limits = rate_limiter._get_limits(key)
        assert limits == (20, 120)


class TestConfigurableRateLimiter:
    """Tests for ConfigurableRateLimiter class."""

    @pytest.fixture
    def base_limiter(self) -> InMemoryRateLimiter:
        """Create a base rate limiter."""
        return InMemoryRateLimiter(default_limit=10, default_time_window=60)

    @pytest.fixture
    def config(self) -> dict[str, Any]:
        """Create a sample configuration."""
        return {
            "rate_limits": {
                "user1": {"limit": 100, "time_window": 300},
                "user2": {"limit": 50, "time_window": 60},
            }
        }

    def test_initialization(
        self, base_limiter: InMemoryRateLimiter, config: dict[str, Any]
    ) -> None:
        """Test ConfigurableRateLimiter initialization."""
        limiter = ConfigurableRateLimiter(base_limiter, config)

        assert limiter._limiter is base_limiter
        assert limiter._config is config

    @pytest.mark.asyncio
    async def test_delegation_to_base_limiter(
        self, base_limiter: InMemoryRateLimiter, config: dict[str, Any]
    ) -> None:
        """Test that ConfigurableRateLimiter delegates to base limiter."""
        limiter = ConfigurableRateLimiter(base_limiter, config)

        # All methods should delegate to the base limiter
        info = await limiter.check_limit("test-key")
        assert isinstance(info, RateLimitInfo)

        await limiter.record_usage("test-key")
        await limiter.reset("test-key")
        await limiter.set_limit("test-key", 20, 60)

    @pytest.mark.asyncio
    async def test_config_with_no_rate_limits(
        self, base_limiter: InMemoryRateLimiter
    ) -> None:
        """Test configuration with no rate limits section."""
        config = {"other_setting": "value"}
        limiter = ConfigurableRateLimiter(base_limiter, config)

        # Should work normally
        info = await limiter.check_limit("test-key")
        assert info.limit == 10  # default from base limiter


class TestCreateRateLimiter:
    """Tests for create_rate_limiter factory function."""

    def test_create_with_dict_config(self) -> None:
        """Test creating rate limiter with dictionary config."""
        config = {
            "rate_limits": {
                "user1": {"limit": 100, "time_window": 300},
            }
        }

        limiter = create_rate_limiter(config)

        assert isinstance(limiter, ConfigurableRateLimiter)

    def test_create_with_app_config_like_object(self) -> None:
        """Test creating rate limiter with AppConfig-like object."""

        class MockConfig:
            default_rate_limit = 100
            default_rate_window = 120

            def to_legacy_config(self):
                return {"rate_limits": {}}

        config = MockConfig()
        limiter = create_rate_limiter(config)

        assert isinstance(limiter, ConfigurableRateLimiter)

    def test_create_with_minimal_config(self) -> None:
        """Test creating rate limiter with minimal config."""
        limiter = create_rate_limiter({})

        assert isinstance(limiter, ConfigurableRateLimiter)

    def test_create_with_non_dict_config(self) -> None:
        """Test creating rate limiter with non-dict config."""

        class MockConfig:
            pass

        limiter = create_rate_limiter(MockConfig())

        assert isinstance(limiter, ConfigurableRateLimiter)
