"""Fake clock utilities for deterministic testing.

This module provides utilities for testing time-dependent code in a
deterministic way, without relying on actual wall-clock time.
"""

from __future__ import annotations

import asyncio
from typing import Any


class FakeClock:
    """A fake clock for deterministic time-based testing.

    This clock allows tests to control time progression explicitly,
    making tests deterministic and fast.
    """

    def __init__(self, initial_time: float = 0.0) -> None:
        """Initialize the fake clock.

        Args:
            initial_time: The initial time value (default: 0.0)
        """
        self._current_time = initial_time
        self._events: list[tuple[float, asyncio.Event]] = []

    def now(self) -> float:
        """Get the current time.

        Returns:
            The current time value
        """
        return self._current_time

    def advance(self, delta: float) -> None:
        """Advance the clock by a given amount.

        Args:
            delta: The amount of time to advance
        """
        if delta < 0:
            raise ValueError("Cannot advance time backwards")

        self._current_time += delta

        # Trigger any events that should fire
        triggered_events = [
            event for time, event in self._events if time <= self._current_time
        ]
        self._events = [
            (time, event) for time, event in self._events if time > self._current_time
        ]

        for event in triggered_events:
            event.set()

    def set_time(self, time: float) -> None:
        """Set the clock to a specific time.

        Args:
            time: The time to set
        """
        if time < self._current_time:
            raise ValueError("Cannot set time backwards")

        self._current_time = time

        # Trigger any events that should fire
        triggered_events = [
            event for event_time, event in self._events if event_time <= time
        ]
        self._events = [
            (event_time, event)
            for event_time, event in self._events
            if event_time > time
        ]

        for event in triggered_events:
            event.set()

    async def sleep(self, duration: float) -> None:
        """Sleep for a given duration (fake).

        This method simulates sleeping by advancing the clock.

        Args:
            duration: The duration to sleep
        """
        target_time = self._current_time + duration
        event = asyncio.Event()
        self._events.append((target_time, event))
        await event.wait()

    def reset(self) -> None:
        """Reset the clock to initial state."""
        self._current_time = 0.0
        self._events.clear()


class FakeClockContext:
    """Context manager for using a fake clock in tests.

    This context manager patches asyncio.sleep and time.time to use
    the fake clock, making all time-dependent code deterministic.
    """

    def __init__(self, clock: FakeClock | None = None) -> None:
        """Initialize the context.

        Args:
            clock: Optional fake clock to use (creates new one if None)
        """
        self.clock = clock or FakeClock()
        self._original_sleep: Any = None
        self._original_time: Any = None

    async def __aenter__(self) -> FakeClock:
        """Enter the context."""
        # Patch asyncio.sleep
        self._original_sleep = asyncio.sleep

        async def fake_sleep(delay: float, result: Any = None) -> Any:
            await self.clock.sleep(delay)
            return result

        asyncio.sleep = fake_sleep  # type: ignore[assignment]

        return self.clock

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit the context."""
        # Restore original functions
        if self._original_sleep is not None:
            asyncio.sleep = self._original_sleep  # type: ignore[assignment]
