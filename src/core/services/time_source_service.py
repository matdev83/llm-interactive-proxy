"""Time source service implementation.

This module provides the default TimeSource implementation that reads from
the system clock, and a TimeOverride context manager for test-controlled time.
"""

from __future__ import annotations

import asyncio
import time
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from typing import Any

from src.core.interfaces.time_source_interface import ITimeSource

# ContextVar for storing override time source in async-safe way
_OVERRIDE_TIME_SOURCE: ContextVar[ITimeSource | None] = ContextVar(
    "override_time_source", default=None
)


class TimeSource(ITimeSource):
    """Default time source implementation using system clock.

    When no override is active, this reads from the real system clock.
    When an override is active (via TimeOverride context manager), it uses
    the override time source instead.
    """

    def now_utc(self) -> datetime:
        """Get the current UTC wall-clock time.

        Returns:
            Current UTC datetime with timezone info
        """
        override = _OVERRIDE_TIME_SOURCE.get()
        if override is not None:
            return override.now_utc()
        return datetime.now(timezone.utc)

    def now_local(self) -> datetime:
        """Get the current local wall-clock time.

        Returns:
            Current local datetime (may be naive, without timezone info)
        """
        override = _OVERRIDE_TIME_SOURCE.get()
        if override is not None:
            return override.now_local()
        return datetime.now()

    def unix_time_s(self) -> float:
        """Get the current time as Unix epoch seconds.

        This value is consistent with now_utc() - both use the same
        conceptual clock.

        Returns:
            Seconds since Unix epoch (1970-01-01 00:00:00 UTC) as float
        """
        override = _OVERRIDE_TIME_SOURCE.get()
        if override is not None:
            return override.unix_time_s()
        return time.time()

    def monotonic_s(self) -> float:
        """Get monotonic time (duration-only, not wall-clock).

        This is suitable for measuring elapsed time but should not be used
        as a wall-clock timestamp for persisted or user-visible data.

        Returns:
            Monotonic time in seconds as float
        """
        override = _OVERRIDE_TIME_SOURCE.get()
        if override is not None:
            return override.monotonic_s()
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        """Sleep for the specified duration.

        Args:
            seconds: Duration to sleep in seconds
        """
        override = _OVERRIDE_TIME_SOURCE.get()
        if override is not None:
            await override.sleep(seconds)
        else:
            await asyncio.sleep(seconds)


class TimeOverride:
    """Context manager for overriding time source in tests.

    This provides an async-safe way to supply a deterministic time source
    for tests without global patching. The override is scoped to the
    context and does not leak to concurrent tests.

    Usage:
        async with TimeOverride(mock_time_source):
            # All TimeSource calls use mock_time_source
            time_source = TimeSource()
            assert time_source.now_utc() == expected_time
    """

    def __init__(self, override_source: ITimeSource) -> None:
        """Initialize the time override context.

        Args:
            override_source: The time source to use within the context
        """
        self._override_source = override_source
        self._token: Token[ITimeSource | None] | None = None

    async def __aenter__(self) -> TimeOverride:
        """Enter the override context."""
        self._token = _OVERRIDE_TIME_SOURCE.set(self._override_source)
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: Any | None,
    ) -> None:
        """Exit the override context."""
        if self._token is not None:
            _OVERRIDE_TIME_SOURCE.reset(self._token)
            self._token = None
