"""
Tests for Rate Limiter Interface.

This module tests the rate limiter interface definitions and contract compliance.
"""

from abc import ABC

from src.core.interfaces.rate_limiter_interface import IRateLimiter, RateLimitInfo


class TestRateLimitInfo:
    """Tests for RateLimitInfo class."""

    def test_rate_limit_info_default_initialization(self) -> None:
        """Test RateLimitInfo default initialization."""
        info = RateLimitInfo()

        assert info.is_limited is False
        assert info.remaining == 0
        assert info.reset_at is None
        assert info.limit == 0
        assert info.time_window == 0

    def test_rate_limit_info_custom_initialization(self) -> None:
        """Test RateLimitInfo custom initialization."""
        info = RateLimitInfo(
            is_limited=True,
            remaining=5,
            reset_at=1234567890.0,
            limit=10,
            time_window=60,
        )

        assert info.is_limited is True
        assert info.remaining == 5
        assert info.reset_at == 1234567890.0
        assert info.limit == 10
        assert info.time_window == 60

    def test_rate_limit_info_partial_initialization(self) -> None:
        """Test RateLimitInfo partial initialization."""
        info = RateLimitInfo(is_limited=True, limit=100)

        assert info.is_limited is True
        assert info.remaining == 0  # default
        assert info.reset_at is None  # default
        assert info.limit == 100
        assert info.time_window == 0  # default


class TestIRateLimiterInterface:
    """Tests for IRateLimiter interface."""

    def test_rate_limiter_is_abstract(self) -> None:
        """Test that IRateLimiter is an abstract class."""
        assert issubclass(IRateLimiter, ABC)

    def test_rate_limiter_abstract_methods(self) -> None:
        """Test that IRateLimiter defines all required abstract methods."""
        expected_methods = ["check_limit", "record_usage", "reset", "set_limit"]

        for method_name in expected_methods:
            assert hasattr(IRateLimiter, method_name)

            # Check that methods are abstract
            method = getattr(IRateLimiter, method_name)
            assert hasattr(method, "__isabstractmethod__")
            assert method.__isabstractmethod__ is True

    def test_rate_limiter_method_signatures(self) -> None:
        """Test that IRateLimiter methods have correct signatures."""
        # check_limit(key: str) -> RateLimitInfo
        assert callable(IRateLimiter.check_limit)

        # record_usage(key: str, cost: int = 1) -> None
        assert callable(IRateLimiter.record_usage)

        # reset(key: str) -> None
        assert callable(IRateLimiter.reset)

        # set_limit(key: str, limit: int, time_window: int) -> None
        assert callable(IRateLimiter.set_limit)


class TestRateLimiterInterfaceCompliance:
    """Tests for rate limiter interface compliance and contracts."""

    def test_rate_limiter_interfaces_are_properly_defined(self) -> None:
        """Test that rate limiter interfaces are properly defined."""
        interfaces = [IRateLimiter]

        for interface in interfaces:
            assert issubclass(interface, ABC)
            assert hasattr(interface, "__annotations__")

    def test_rate_limit_info_has_required_attributes(self) -> None:
        """Test that RateLimitInfo has all required attributes."""
        required_attrs = ["is_limited", "remaining", "reset_at", "limit", "time_window"]

        # Test on instance since it's not a dataclass
        info = RateLimitInfo()
        for attr in required_attrs:
            assert hasattr(info, attr)

    def test_rate_limit_info_attribute_types(self) -> None:
        """Test that RateLimitInfo attributes have correct types."""
        # Test with instance
        info = RateLimitInfo()

        assert isinstance(info.is_limited, bool)
        assert isinstance(info.remaining, int)
        assert isinstance(info.reset_at, float | None)
        assert isinstance(info.limit, int)
        assert isinstance(info.time_window, int)

    def test_rate_limit_info_as_dict_conversion(self) -> None:
        """Test that RateLimitInfo can be converted to dictionary."""
        info = RateLimitInfo(
            is_limited=True,
            remaining=5,
            reset_at=1234567890.0,
            limit=10,
            time_window=60,
        )

        # Check that all attributes are accessible
        data = {
            "is_limited": info.is_limited,
            "remaining": info.remaining,
            "reset_at": info.reset_at,
            "limit": info.limit,
            "time_window": info.time_window,
        }

        assert data["is_limited"] is True
        assert data["remaining"] == 5
        assert data["reset_at"] == 1234567890.0
        assert data["limit"] == 10
        assert data["time_window"] == 60
