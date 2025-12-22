"""
Rate Limiter Service

Implements the IRateLimiter interface for controlling API request rates.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
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
        self._usage_last_access: dict[str, float] = (
            {}
        )  # Track last access time for cleanup
        self._limits: dict[str, tuple[int, int]] = {}  # Dict[str, (int, int)]
        self._limits_last_access: dict[str, float] = (
            {}
        )  # Track last access time for cleanup
        self._cooldowns: dict[str, float] = {}

        # Default limits (operations per time window)
        self._default_limit = default_limit
        self._default_time_window = default_time_window
        # Maximum number of usage entries to prevent unbounded growth
        self._max_usage_entries = 10000
        # TTL for usage entries: remove if not accessed for 1 hour
        self._usage_ttl_seconds = 3600
        # Maximum number of custom limits to prevent unbounded growth
        self._max_limits = 10000
        # TTL for limits: remove if not accessed for 24 hours
        self._limits_ttl_seconds = 24 * 3600

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

        # Track access time for cleanup
        self._usage_last_access[key] = now

        # Get the timestamps of previous usages
        timestamps = self._usage.get(key, [])

        # Get the limits for this key (or use defaults)
        limit, time_window = self._get_limits(key)

        # Filter out timestamps that are outside the time window
        cutoff = now - time_window
        current = [ts for ts in timestamps if ts > cutoff]

        # Update timestamps list (removing expired ones)
        # Remove key from dict if all timestamps expired to prevent memory leak
        if current:
            self._usage[key] = current
        elif key in self._usage:
            # All timestamps expired - remove key to prevent unbounded growth
            del self._usage[key]
            self._usage_last_access.pop(key, None)
            # Also clean up custom limits if no usage data exists
            if key in self._limits:
                del self._limits[key]
                self._limits_last_access.pop(key, None)

        # Clean up stale usage entries periodically to prevent memory leak
        if len(self._usage) > self._max_usage_entries:
            await self._cleanup_stale_usage_locked(now)

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

        # Clean up expired cooldowns periodically to prevent memory leak
        # Cleanup when cooldowns dict grows large (every 100 entries) to avoid overhead
        # This prevents unbounded growth while keeping cleanup overhead low
        if len(self._cooldowns) > 100:
            expired_cooldowns = [
                k for k, expiry in self._cooldowns.items() if now >= expiry
            ]
            for expired_key in expired_cooldowns:
                self._cooldowns.pop(expired_key, None)

        # Clean up unused limits periodically to prevent memory leak
        # Track access time when limits are retrieved (for cleanup)
        if key in self._limits:
            self._limits_last_access[key] = now

        # Cleanup when limits dict grows large (every 1000 entries) to avoid overhead
        # This prevents unbounded growth while keeping cleanup overhead low
        if len(self._limits) > 1000:
            await self._cleanup_unused_limits_locked(now)

        cooldown_until = self._cooldowns.get(key)
        if cooldown_until is not None:
            if now >= cooldown_until:
                self._cooldowns.pop(key, None)
            else:
                is_limited = True
                remaining = 0
                reset_at = cooldown_until

        if logger.isEnabledFor(logging.DEBUG):
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

        # Track access time for cleanup
        self._usage_last_access[key] = now

        # Check if we need to evict old entries before adding new one
        if key not in self._usage and len(self._usage) >= self._max_usage_entries:
            await self._cleanup_stale_usage_locked(now)
            # If still at capacity, evict oldest
            if len(self._usage) >= self._max_usage_entries:
                await self._evict_oldest_usage_locked()

        # Get existing timestamps and clean up expired ones before adding new entries
        # This prevents unbounded list growth when record_usage() is called frequently
        # without check_limit() being called to clean up expired timestamps
        timestamps = self._usage.get(key, [])
        if timestamps:
            # Get the limits for this key to determine time window
            limit, time_window = self._get_limits(key)
            cutoff = now - time_window
            # Filter out expired timestamps to prevent unbounded growth
            timestamps = [ts for ts in timestamps if ts > cutoff]

        # Add new timestamps (one for each cost unit)
        for _ in range(cost):
            timestamps.append(now)

        # Update usage data (remove key if all timestamps expired)
        if timestamps:
            self._usage[key] = timestamps
        elif key in self._usage:
            # All timestamps expired - remove key to prevent unbounded growth
            del self._usage[key]
            self._usage_last_access.pop(key, None)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Recorded usage for {key}: cost={cost}")

    async def reset(self, key: str) -> None:
        """Reset rate limit counters for the given key.

        Args:
            key: The key to reset
        """
        if key in self._usage:
            del self._usage[key]
            self._usage_last_access.pop(key, None)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Reset rate limit counters for {key}")
        if key in self._cooldowns:
            self._cooldowns.pop(key, None)
        # Note: We don't remove custom limits on reset as they may be intentionally persistent

    async def set_limit(self, key: str, limit: int, time_window: int) -> None:
        """Set a custom rate limit for the given key.

        Args:
            key: The key to set limits for
            limit: The maximum number of operations
            time_window: The time window in seconds
        """
        now = time.time()

        # Enforce max limits with LRU eviction
        if len(self._limits) >= self._max_limits and key not in self._limits:
            await self._evict_oldest_limit_locked(now)

        self._limits[key] = (limit, time_window)
        self._limits_last_access[key] = now
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Set custom rate limit for {key}: {limit}/{time_window}s")

    async def apply_cooldown(self, key: str, cooldown_seconds: int) -> None:
        """Force a temporary cooldown for the key."""
        if cooldown_seconds <= 0:
            return

        now = time.time()
        new_expiry = now + cooldown_seconds
        current_expiry = self._cooldowns.get(key)

        if current_expiry is None or new_expiry > current_expiry:
            self._cooldowns[key] = new_expiry
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Applied cooldown for %s until %s",
                    key,
                    datetime.fromtimestamp(new_expiry).isoformat(),
                )

    def _get_limits(self, key: str) -> tuple[int, int]:
        """Get the limits for a key (or default if not set).

        Args:
            key: The key to get limits for

        Returns:
            A tuple of (limit, time_window)
        """
        if key in self._limits:
            # Track access time for cleanup
            self._limits_last_access[key] = time.time()
        return self._limits.get(key, (self._default_limit, self._default_time_window))

    async def _cleanup_unused_limits_locked(self, now: float) -> None:
        """Remove unused limits that haven't been accessed recently.

        This prevents unbounded growth of the _limits dictionary when limits
        are set but never used, or when they become stale.

        Args:
            now: Current timestamp
        """
        cutoff = now - self._limits_ttl_seconds
        expired_keys = []
        for k, last_access in self._limits_last_access.items():
            if last_access < cutoff:
                expired_keys.append((k, last_access))

        for expired_key, last_access in expired_keys:
            self._limits.pop(expired_key, None)
            self._limits_last_access.pop(expired_key, None)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Removed unused limit for key %s (last access: %.1fs ago)",
                    expired_key,
                    now - last_access,
                )

    async def _evict_oldest_limit_locked(self, now: float) -> None:
        """Evict the oldest unused limit when max_limits is reached.

        Uses LRU eviction based on last access time.

        Args:
            now: Current timestamp
        """
        if not self._limits:
            return

        # Find the key with oldest last access time
        oldest_key = min(self._limits_last_access.items(), key=lambda x: x[1])[0]
        self._limits.pop(oldest_key, None)
        self._limits_last_access.pop(oldest_key, None)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Evicted oldest limit for key %s (max_limits=%d reached)",
                oldest_key,
                self._max_limits,
            )

    async def _cleanup_stale_usage_locked(self, now: float) -> None:
        """Remove stale usage entries that haven't been accessed recently.

        This prevents unbounded growth of the _usage dictionary when many
        unique keys are used but become inactive.

        Args:
            now: Current timestamp
        """
        cutoff = now - self._usage_ttl_seconds
        expired_keys = [
            (k, last_access)
            for k, last_access in self._usage_last_access.items()
            if last_access < cutoff
        ]

        for expired_key, last_access in expired_keys:
            self._usage.pop(expired_key, None)
            self._usage_last_access.pop(expired_key, None)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Removed stale usage entry for key %s (last access: %.1fs ago)",
                    expired_key,
                    now - last_access,
                )

    async def _evict_oldest_usage_locked(self) -> None:
        """Evict the oldest usage entry when max_usage_entries is reached.

        Uses LRU eviction based on last access time.

        This prevents unbounded growth by removing least recently used entries.
        """
        if not self._usage_last_access:
            return

        # Find the key with oldest last access time
        oldest_key = min(self._usage_last_access.items(), key=lambda x: x[1])[0]
        self._usage.pop(oldest_key, None)
        self._usage_last_access.pop(oldest_key, None)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Evicted oldest usage entry for key %s (max_usage_entries=%d reached)",
                oldest_key,
                self._max_usage_entries,
            )


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

    async def apply_cooldown(self, key: str, cooldown_seconds: int) -> None:
        """Forward cooldown applications to base limiter."""
        await self._ensure_config_applied()
        await self._limiter.apply_cooldown(key, cooldown_seconds)

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
            logger.warning("Rate limit configuration is not a mapping: %r", rate_limits)
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
    default_limit = config_dict.get("default_rate_limit", 60)
    default_time_window = config_dict.get("default_rate_window", 60)

    # Create base limiter
    base_limiter = InMemoryRateLimiter(
        default_limit=default_limit, default_time_window=default_time_window
    )

    # Wrap with configurable limiter
    return ConfigurableRateLimiter(base_limiter, config_dict)
