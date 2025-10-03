"""
Rate Limiter Service

Implements the IRateLimiter interface for controlling API request rates.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from src.core.interfaces.rate_limiter_interface import IRateLimiter, RateLimitInfo

logger = logging.getLogger(__name__)


class InMemoryRateLimiter(IRateLimiter):
    """In-memory implementation of rate limiting.

    This implementation stores rate limit data in memory and is suitable
    for single-instance deployments.
    """

    def __init__(self, default_limit: int = 60, default_time_window: int = 60) -> None:
        """Initialize the rate limiter.

        Args:
            default_limit: Default operations per time window
            default_time_window: Default time window in seconds
        """
        self._usage: dict[str, list[float]] = {}  # Dict[str, List[float]]
        self._limits: dict[str, tuple[int, int]] = {}  # Dict[str, (int, int)]

        # Default limits (operations per time window)
        self._default_limit = default_limit
        self._default_time_window = default_time_window

        logger.info(
            f"Initialized InMemoryRateLimiter with defaults: {default_limit}/{default_time_window}s"
        )

    async def check_limit(self, key: str) -> RateLimitInfo:
        """Check if the given key is rate limited.

        Args:
            key: The key to check

        Returns:
            RateLimitInfo with rate limit status
        """
        now = time.time()

        # Get the timestamps of previous usages
        timestamps = self._usage.get(key, [])

        # Get the limits for this key (or use defaults)
        limit, time_window = self._get_limits(key)

        # Filter out timestamps that are outside the time window
        cutoff = now - time_window
        current = [ts for ts in timestamps if ts > cutoff]

        # Update timestamps list (removing expired ones)
        self._usage[key] = current

        # Calculate remaining
        used = len(current)
        remaining = max(0, limit - used)

        # Determine if rate limited
        is_limited = used >= limit

        # Calculate reset time
        reset_at = None
        if current and is_limited:
            # Time when the oldest request falls out of the window
            reset_at = current[0] + time_window

        logger.debug(
            f"Rate limit check: {key} - {used}/{limit} used, limited: {is_limited}"
        )

        return RateLimitInfo(
            is_limited=is_limited,
            remaining=remaining,
            reset_at=reset_at,
            limit=limit,
            time_window=time_window,
        )

    async def record_usage(self, key: str, cost: int = 1) -> None:
        """Record usage for the given key.

        Args:
            key: The key to record usage for
            cost: The cost of the operation
        """
        now = time.time()

        # Get existing timestamps
        timestamps = self._usage.get(key, [])

        # Add new timestamps (one for each cost unit)
        for _ in range(cost):
            timestamps.append(now)

        # Update usage data
        self._usage[key] = timestamps

        logger.debug(f"Recorded usage for {key}: cost={cost}")

    async def reset(self, key: str) -> None:
        """Reset rate limit counters for the given key.

        Args:
            key: The key to reset
        """
        if key in self._usage:
            self._usage[key] = []
            logger.debug(f"Reset rate limit counters for {key}")

    async def set_limit(self, key: str, limit: int, time_window: int) -> None:
        """Set a custom rate limit for the given key.

        Args:
            key: The key to set limits for
            limit: The maximum number of operations
            time_window: The time window in seconds
        """
        self._limits[key] = (limit, time_window)
        logger.debug(f"Set custom rate limit for {key}: {limit}/{time_window}s")

    def _get_limits(self, key: str) -> tuple[int, int]:
        """Get the limits for a key (or default if not set).

        Args:
            key: The key to get limits for

        Returns:
            A tuple of (limit, time_window)
        """
        return self._limits.get(key, (self._default_limit, self._default_time_window))


class ConfigurableRateLimiter(IRateLimiter):
    """Rate limiter that loads configuration from app config.

    This implementation wraps another rate limiter and configures it
    based on app configuration.
    """

    def __init__(self, base_limiter: IRateLimiter, config: dict[str, Any]) -> None:
        """Initialize the rate limiter.

        Args:
            base_limiter: The base rate limiter to use
            config: Configuration dictionary
        """
        self._limiter = base_limiter
        self._config = config
        self._config_applied = False
        self._config_lock: asyncio.Lock | None = None

    async def check_limit(self, key: str) -> RateLimitInfo:
        """Check if the given key is rate limited.

        Args:
            key: The key to check

        Returns:
            RateLimitInfo with rate limit status
        """
        await self._ensure_config_applied()
        return await self._limiter.check_limit(key)

    async def record_usage(self, key: str, cost: int = 1) -> None:
        """Record usage for the given key.

        Args:
            key: The key to record usage for
            cost: The cost of the operation
        """
        await self._ensure_config_applied()
        await self._limiter.record_usage(key, cost)

    async def reset(self, key: str) -> None:
        """Reset rate limit counters for the given key.

        Args:
            key: The key to reset
        """
        await self._ensure_config_applied()
        await self._limiter.reset(key)

    async def set_limit(self, key: str, limit: int, time_window: int) -> None:
        """Set a custom rate limit for the given key.

        Args:
            key: The key to set limits for
            limit: The maximum number of operations
            time_window: The time window in seconds
        """
        await self._ensure_config_applied()
        await self._limiter.set_limit(key, limit, time_window)

    async def _ensure_config_applied(self) -> None:
        """Apply configuration once before delegating to the base limiter."""
        if self._config_applied:
            return

        if self._config_lock is None:
            self._config_lock = asyncio.Lock()

        async with self._config_lock:
            if self._config_applied:
                return
            await self._apply_config()
            self._config_applied = True

    async def _apply_config(self) -> None:
        """Apply configuration to the rate limiter."""
        rate_limits = self._config.get("rate_limits", {})
        if not isinstance(rate_limits, dict):
            logger.warning(
                "Rate limit configuration is not a mapping: %r", rate_limits
            )
            return

        default_limit = getattr(self._limiter, "_default_limit", 60)
        default_time_window = getattr(self._limiter, "_default_time_window", 60)

        applied = 0
        for key, settings in rate_limits.items():
            if not isinstance(settings, dict):
                logger.warning(
                    "Skipping rate limit for %s because settings are not a mapping: %r",
                    key,
                    settings,
                )
                continue

            limit_raw = settings.get("limit", default_limit)
            window_raw = settings.get("time_window", default_time_window)

            try:
                limit = int(limit_raw)
                time_window = int(window_raw)
            except (TypeError, ValueError):
                logger.warning(
                    "Skipping rate limit for %s due to invalid values limit=%r, time_window=%r",
                    key,
                    limit_raw,
                    window_raw,
                )
                continue

            if limit <= 0 or time_window <= 0:
                logger.warning(
                    "Skipping rate limit for %s because values must be positive: %s/%s",
                    key,
                    limit,
                    time_window,
                )
                continue

            try:
                await self._limiter.set_limit(key, limit, time_window)
                applied += 1
                logger.info(
                    "Applied configured rate limit for %s: %s requests per %ss",
                    key,
                    limit,
                    time_window,
                )
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.exception(
                    "Failed to apply configured rate limit for %s: %s", key, exc
                )

        if applied and logger.isEnabledFor(logging.INFO):
            logger.info("Applied %d configured rate limit entries", applied)


# Alias for backward compatibility
RateLimiter = InMemoryRateLimiter


def create_rate_limiter(config: Any) -> IRateLimiter:
    """Create a rate limiter based on configuration.

    Args:
        config: Configuration object (AppConfig or dict)

    Returns:
        A configured rate limiter
    """
    # Convert AppConfig to dictionary if needed
    if hasattr(config, "to_legacy_config"):
        config_dict = config.to_legacy_config()
    elif isinstance(config, dict):
        config_dict = config
    else:
        config_dict = {}

    # Get rate limiter configuration with defaults
    default_limit = (
        config.default_rate_limit if hasattr(config, "default_rate_limit") else 60
    )
    default_time_window = (
        config.default_rate_window if hasattr(config, "default_rate_window") else 60
    )

    # Create base limiter
    base_limiter = InMemoryRateLimiter(
        default_limit=default_limit, default_time_window=default_time_window
    )

    # Wrap with configurable limiter
    return ConfigurableRateLimiter(base_limiter, config_dict)
