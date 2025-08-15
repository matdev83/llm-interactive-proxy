import time

from src.core.interfaces.rate_limiter import IRateLimiter, RateLimitInfo


class InMemoryRateLimiter(IRateLimiter):
    """
    An in-memory implementation of the rate limiter.
    """

    def __init__(self, default_limit: int = 100, default_period: int = 60):
        self._limits: dict[str, dict] = {}
        self._default_limit = default_limit
        self._default_period = default_period

    async def set_limit(self, key: str, limit: int, period: int) -> None:
        """
        Set a rate limit for a specific key.

        Args:
            key: The rate limit key
            limit: The maximum number of requests allowed
            period: The time period in seconds
        """
        now = time.time()
        self._limits[key] = {
            "limit": limit,
            "period": period,
            "remaining": limit,
            "reset_at": now + period,
        }

    async def reset(self, key: str) -> None:
        """
        Reset the rate limit for a specific key.

        Args:
            key: The rate limit key
        """
        if key in self._limits:
            now = time.time()
            self._limits[key]["remaining"] = self._limits[key]["limit"]
            self._limits[key]["reset_at"] = now + self._limits[key]["period"]

    async def check_limit(self, key: str) -> RateLimitInfo:
        now = time.time()
        limit_info = self._limits.get(
            key,
            {
                "limit": self._default_limit,
                "period": self._default_period,
                "remaining": self._default_limit,
                "reset_at": now + self._default_period,
            },
        )

        if now > limit_info["reset_at"]:
            limit_info["remaining"] = limit_info["limit"]
            limit_info["reset_at"] = now + limit_info["period"]

        is_limited = limit_info["remaining"] <= 0

        rate_limit_info = RateLimitInfo()
        rate_limit_info.is_limited = is_limited
        rate_limit_info.limit = limit_info["limit"]
        rate_limit_info.remaining = limit_info["remaining"]
        rate_limit_info.reset_at = limit_info["reset_at"]

        return rate_limit_info

    async def record_usage(self, key: str, cost: int = 1) -> None:
        if key in self._limits:
            self._limits[key]["remaining"] -= cost
        else:
            now = time.time()
            self._limits[key] = {
                "limit": self._default_limit,
                "period": self._default_period,
                "remaining": self._default_limit - cost,
                "reset_at": now + self._default_period,
            }
