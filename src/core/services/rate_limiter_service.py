from __future__ import annotations

import logging
import time
from typing import Any

from src.core.interfaces.rate_limiter_interface import IRateLimiter, RateLimitInfo

logger = logging.getLogger(__name__)


class InMemoryRateLimiter(IRateLimiter):
    def __init__(self, default_limit: int = 60, default_time_window: int = 60) -> None:
        self._usage: dict[str, list[float]] = {}
        self._limits: dict[str, tuple[int, int]] = {}
        self._default_limit = default_limit
        self._default_time_window = default_time_window

    async def check_limit(self, key: str) -> RateLimitInfo:
        now = time.time()
        timestamps = self._usage.get(key, [])
        limit, time_window = self._get_limits(key)
        cutoff = now - time_window
        current = [ts for ts in timestamps if ts > cutoff]
        self._usage[key] = current
        used = len(current)
        remaining = max(0, limit - used)
        is_limited = used >= limit
        reset_at = None
        if current and is_limited:
            reset_at = current[0] + time_window
        return RateLimitInfo(is_limited=is_limited, remaining=remaining, reset_at=reset_at, limit=limit, time_window=time_window)

    async def record_usage(self, key: str, cost: int = 1) -> None:
        now = time.time()
        timestamps = self._usage.get(key, [])
        for _ in range(cost):
            timestamps.append(now)
        self._usage[key] = timestamps

    async def reset(self, key: str) -> None:
        if key in self._usage:
            self._usage[key] = []

    async def set_limit(self, key: str, limit: int, time_window: int) -> None:
        self._limits[key] = (limit, time_window)

    def _get_limits(self, key: str) -> tuple[int, int]:
        return self._limits.get(key, (self._default_limit, self._default_time_window))


class ConfigurableRateLimiter(IRateLimiter):
    def __init__(self, base_limiter: IRateLimiter, config: dict[str, Any]) -> None:
        self._limiter = base_limiter
        self._config = config

    async def check_limit(self, key: str) -> RateLimitInfo:
        return await self._limiter.check_limit(key)

    async def record_usage(self, key: str, cost: int = 1) -> None:
        await self._limiter.record_usage(key, cost)

    async def reset(self, key: str) -> None:
        await self._limiter.reset(key)

    async def set_limit(self, key: str, limit: int, time_window: int) -> None:
        await self._limiter.set_limit(key, limit, time_window)

RateLimiter = InMemoryRateLimiter

def create_rate_limiter(config: Any) -> IRateLimiter:
    default_limit = config.default_rate_limit if hasattr(config, "default_rate_limit") else 60
    default_time_window = config.default_rate_window if hasattr(config, "default_rate_window") else 60
    base_limiter = InMemoryRateLimiter(default_limit=default_limit, default_time_window=default_time_window)
    return ConfigurableRateLimiter(base_limiter, config)


