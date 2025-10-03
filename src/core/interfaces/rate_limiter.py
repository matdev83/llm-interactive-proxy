from __future__ import annotations

from abc import ABC, abstractmethod


class RateLimitInfo:
    """Information about rate limit status."""

    is_limited: bool
    remaining: int
    reset_at: float | None = None
    limit: int
    time_window: int  # in seconds

    def __init__(
        self,
        is_limited: bool = False,
        remaining: int = 0,
        reset_at: float | None = None,
        limit: int = 0,
        time_window: int = 0,
    ) -> None:
        self.is_limited = is_limited
        self.remaining = remaining
        self.reset_at = reset_at
        self.limit = limit
        self.time_window = time_window


class IRateLimiter(ABC):
    """Interface for rate limiting operations.

    This interface defines the contract for components that implement
    rate limiting for API calls.
    """

    @abstractmethod
    async def check_limit(self, key: str) -> RateLimitInfo:
        """Check if the given key is rate limited.

        Args:
            key: The key to check (typically user ID or API key)

        Returns:
            RateLimitInfo with rate limit status
        """

    @abstractmethod
    async def record_usage(self, key: str, cost: int = 1) -> None:
        """Record usage for the given key.

        Args:
            key: The key to record usage for
            cost: The cost of the operation (default: 1)
        """

    @abstractmethod
    async def reset(self, key: str) -> None:
        """Reset rate limit counters for the given key.

        Args:
            key: The key to reset
        """

    @abstractmethod
    async def set_limit(self, key: str, limit: int, time_window: int) -> None:
        """Set a custom rate limit for the given key.

        Args:
            key: The key to set limits for
            limit: The maximum number of operations
            time_window: The time window in seconds
        """
