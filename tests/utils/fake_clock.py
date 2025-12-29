"""Fake clock utilities for deterministic testing.

This module provides utilities for testing time-dependent code in a
deterministic way, without relying on actual wall-clock time.
"""

from __future__ import annotations

import asyncio
import contextlib
import time as time_module
from collections.abc import Awaitable
from contextvars import ContextVar, Token
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

    def time(self) -> float:
        """Get the current time (alias for now()).

        Returns:
            The current time value
        """
        return self.now()

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

    def sleep(self, duration: float, result: Any = None) -> Awaitable[Any]:
        """Sleep for a given duration (fake).

        The sleep event is registered immediately when this method is called,
        not when the returned awaitable is first awaited. This makes fake-time
        deterministic for patterns like:

            sleep_task = asyncio.create_task(asyncio.sleep(x))
            clock.advance(x)
            await sleep_task
        """
        target_time = self._current_time + duration
        event = asyncio.Event()
        self._events.append((target_time, event))

        if target_time <= self._current_time:
            event.set()

        async def _wait() -> Any:
            try:
                await event.wait()
                return result
            finally:
                self._events = [
                    (event_time, pending)
                    for event_time, pending in self._events
                    if pending is not event
                ]

        return _wait()

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
        self._owns_clock = clock is None
        self.clock = clock or FakeClock()
        self._token: Token[FakeClock | None] | None = None

    _PATCHED: bool = False
    _ACTIVE_CLOCK: ContextVar[FakeClock | None] = ContextVar(
        "fake_clock_active", default=None
    )
    _ORIGINAL_ASYNCIO_SLEEP: Any = None
    _ORIGINAL_TIME: Any = None
    _SLEEP_WRAPPER: Any = None
    _TIME_WRAPPER: Any = None

    @classmethod
    def _ensure_patched(cls) -> None:
        # Capture originals once (before we replace them with wrappers).
        if cls._ORIGINAL_ASYNCIO_SLEEP is None:
            cls._ORIGINAL_ASYNCIO_SLEEP = asyncio.sleep
        if cls._ORIGINAL_TIME is None:
            cls._ORIGINAL_TIME = time_module.time

        # Create stable wrapper functions once; re-install them if another test
        # overwrote asyncio.sleep/time.time in the meantime.
        if cls._SLEEP_WRAPPER is None:

            def _sleep(delay: float, result: Any = None) -> Any:
                if delay <= 0:
                    return cls._ORIGINAL_ASYNCIO_SLEEP(0, result=result)  # type: ignore[misc]
                clock = cls._ACTIVE_CLOCK.get()
                if clock is None:
                    return cls._ORIGINAL_ASYNCIO_SLEEP(delay, result=result)  # type: ignore[misc]
                return clock.sleep(delay, result=result)

            cls._SLEEP_WRAPPER = _sleep

        if cls._TIME_WRAPPER is None:

            def _time() -> float:
                clock = cls._ACTIVE_CLOCK.get()
                if clock is None:
                    return float(cls._ORIGINAL_TIME())
                return float(clock.now())

            cls._TIME_WRAPPER = _time

        if asyncio.sleep is not cls._SLEEP_WRAPPER:
            asyncio.sleep = cls._SLEEP_WRAPPER  # type: ignore[assignment]
        if time_module.time is not cls._TIME_WRAPPER:
            time_module.time = cls._TIME_WRAPPER  # type: ignore[assignment]

        cls._PATCHED = True

    async def __aenter__(self) -> FakeClock:
        """Enter the context."""
        self._ensure_patched()
        self._token = self._ACTIVE_CLOCK.set(self.clock)

        # When we create the clock internally (common case), start from "now" so
        # that advancing time preserves epoch-based semantics for code that
        # compares against real timestamps.
        if self._owns_clock and self.clock.now() == 0.0:
            with contextlib.suppress(Exception):
                self.clock.set_time(float(self._ORIGINAL_TIME()))

        return self.clock

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit the context."""
        if self._token is not None:
            self._ACTIVE_CLOCK.reset(self._token)
            self._token = None
