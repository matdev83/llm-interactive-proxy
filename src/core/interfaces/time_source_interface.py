"""Time source interface for deterministic time access.

This module defines the interface for accessing wall-clock time in a way that
can be overridden by tests for deterministic behavior.
"""

from __future__ import annotations

import abc
from datetime import datetime


class ITimeSource(abc.ABC):
    """Interface for accessing wall-clock time.

    This interface provides a single boundary for time access that can be
    overridden by tests to ensure deterministic behavior.
    """

    @abc.abstractmethod
    def now_utc(self) -> datetime:
        """Get the current UTC wall-clock time.

        Returns:
            Current UTC datetime with timezone info
        """
        ...

    @abc.abstractmethod
    def now_local(self) -> datetime:
        """Get the current local wall-clock time.

        Returns:
            Current local datetime (may be naive, without timezone info)
        """
        ...

    @abc.abstractmethod
    def unix_time_s(self) -> float:
        """Get the current time as Unix epoch seconds.

        This value should be consistent with now_utc() - i.e., the same
        conceptual clock is used for both.

        Returns:
            Seconds since Unix epoch (1970-01-01 00:00:00 UTC) as float
        """
        ...

    @abc.abstractmethod
    def monotonic_s(self) -> float:
        """Get monotonic time (duration-only, not wall-clock).

        This is suitable for measuring elapsed time but should not be used
        as a wall-clock timestamp for persisted or user-visible data.

        Returns:
            Monotonic time in seconds as float
        """
        ...

    @abc.abstractmethod
    async def sleep(self, seconds: float) -> None:
        """Sleep for the specified duration.

        Args:
            seconds: Duration to sleep in seconds
        """
        ...
