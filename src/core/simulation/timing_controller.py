"""
Timing controller for replay synchronization.

Manages timing for accurate replay of captured traffic.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field


@dataclass
class TimingController:
    """Controls timing for replay of captured traffic.

    Provides methods to calculate delays and wait for the appropriate
    time before replaying each entry.
    """

    speed_multiplier: float = 1.0
    """Speed multiplier for replay. 1.0 = realtime, 2.0 = 2x speed, 0.5 = half speed."""

    min_delay: float = 0.0
    """Minimum delay between entries in seconds."""

    max_delay: float = 30.0
    """Maximum delay between entries in seconds (caps long pauses)."""

    _start_time: float = field(default=0.0, init=False)
    _reference_timestamp: float = field(default=0.0, init=False)
    _last_replay_time: float = field(default=0.0, init=False)

    def start(self, reference_timestamp: float) -> None:
        """Start the timing controller with a reference timestamp.

        Args:
            reference_timestamp: The timestamp of the first entry in the capture
        """
        self._start_time = time.time()
        self._reference_timestamp = reference_timestamp
        self._last_replay_time = self._start_time

    def calculate_delay(self, entry_timestamp: float) -> float:
        """Calculate the delay needed before replaying an entry.

        Args:
            entry_timestamp: The timestamp of the entry to replay

        Returns:
            Delay in seconds (adjusted for speed multiplier and bounds)
        """
        if self._reference_timestamp == 0:
            return 0.0

        # Calculate the target delay based on original timing
        original_delta = entry_timestamp - self._reference_timestamp
        target_wall_time = self._start_time + (original_delta / self.speed_multiplier)

        # Calculate how long we need to wait from now
        current_time = time.time()
        delay = target_wall_time - current_time

        # Apply bounds
        delay = max(self.min_delay, min(self.max_delay, delay))

        return max(0.0, delay)

    async def wait_for_entry(self, entry_timestamp: float) -> float:
        """Wait for the appropriate time to replay an entry.

        Args:
            entry_timestamp: The timestamp of the entry to replay

        Returns:
            Actual delay that was waited (in seconds)
        """
        delay = self.calculate_delay(entry_timestamp)
        if delay > 0:
            await asyncio.sleep(delay)
        actual_delay = time.time() - self._last_replay_time
        self._last_replay_time = time.time()
        return actual_delay

    def get_elapsed_time(self) -> float:
        """Get elapsed time since start.

        Returns:
            Elapsed time in seconds
        """
        if self._start_time == 0:
            return 0.0
        return time.time() - self._start_time

    def reset(self) -> None:
        """Reset the timing controller."""
        self._start_time = 0.0
        self._reference_timestamp = 0.0
        self._last_replay_time = 0.0
