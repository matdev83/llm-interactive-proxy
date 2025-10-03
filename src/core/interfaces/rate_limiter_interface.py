from __future__ import annotations

from abc import ABC, abstractmethod


class RateLimitInfo:
    is_limited: bool
    remaining: int
    reset_at: float | None = None
    limit: int
    time_window: int

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
    @abstractmethod
    async def check_limit(self, key: str) -> RateLimitInfo:
        pass

    @abstractmethod
    async def record_usage(self, key: str, cost: int = 1) -> None:
        pass

    @abstractmethod
    async def reset(self, key: str) -> None:
        pass

    @abstractmethod
    async def set_limit(self, key: str, limit: int, time_window: int) -> None:
        pass
