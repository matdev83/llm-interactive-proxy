"""Thread-safe state store wrapper for SSO web interface.

This module provides a thread-safe wrapper for OAuth state and login session stores
to prevent race conditions during concurrent authentication flows.
"""

import asyncio
from typing import Any


class StateStore:
    """Thread-safe wrapper for OAuth state store."""

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 900):
        self._store: dict[str, str | dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds

    async def get(self, key: str) -> str | dict[str, Any] | None:
        """Get value by key."""
        async with self._lock:
            return self._store.get(key)

    async def set(self, key: str, value: str | dict[str, Any]) -> None:
        """Set value by key, cleaning up expired entries first."""
        await self._cleanup_expired()
        async with self._lock:
            self._store[key] = value

    async def pop(
        self, key: str, default: str | dict[str, Any] | None = None
    ) -> str | dict[str, Any] | None:
        """Pop value by key."""
        async with self._lock:
            return self._store.pop(key, default)

    async def _cleanup_expired(self) -> None:
        """Remove expired entries and enforce max size."""
        import time

        now = time.time()

        async with self._lock:
            # Remove expired entries
            expired_keys = [
                key
                for key, value in self._store.items()
                if isinstance(value, dict)
                and now - value.get("_created_at", 0) > self._ttl_seconds
            ]
            for key in expired_keys:
                del self._store[key]

            # Enforce max size (remove oldest first)
            if len(self._store) > self._max_size:
                sorted_items = sorted(
                    [
                        (k, v)
                        for k, v in self._store.items()
                        if isinstance(v, dict) and "_created_at" in v
                    ],
                    key=lambda x: x[1].get("_created_at", 0),
                )
                to_remove = len(self._store) - self._max_size
                for key, _ in sorted_items[:to_remove]:
                    del self._store[key]
