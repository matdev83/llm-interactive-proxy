"""Session state tracking for test execution reminder system."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class TestExecutionSessionState:
    """State tracking for test execution reminder in a single session.

    This tracks whether files have been modified since the last test run,
    maintaining a "dirty state" indicator that triggers steering interventions
    when agents attempt to complete tasks without running tests.
    """

    is_dirty: bool = False
    """Whether files have been modified since last test run."""

    last_modification_time: float = field(default_factory=lambda: time.time())
    """Timestamp of last file modification."""

    last_test_time: float = 0.0
    """Timestamp of last test execution."""

    last_seen: float = field(default_factory=lambda: time.time())
    """Timestamp of last activity (for TTL cleanup)."""

    modification_count: int = 0
    """Number of modifications since last test run."""

    def mark_dirty(self) -> None:
        """Mark the session as dirty (files modified)."""
        self.is_dirty = True
        self.last_modification_time = time.time()
        self.last_seen = time.time()
        self.modification_count += 1

    def mark_clean(self) -> None:
        """Mark the session as clean (tests run)."""
        self.is_dirty = False
        self.last_test_time = time.time()
        self.last_seen = time.time()
        self.modification_count = 0

    def update_last_seen(self) -> None:
        """Update the last seen timestamp."""
        self.last_seen = time.time()
