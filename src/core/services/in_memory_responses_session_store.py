"""In-process TTL session store for Responses API output item linkage."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass

from src.core.domain.responses_domain import ResponsesOutputItem
from src.core.domain.responses_resolved_session import ResponsesResolvedSession

logger = logging.getLogger(__name__)


@dataclass
class _SessionEntry:
    output_items: list[ResponsesOutputItem]
    instructions: str | None
    expires_at: float


class InMemoryResponsesSessionStore:
    def __init__(self, *, default_ttl_seconds: int = 3600) -> None:
        self._default_ttl_seconds = default_ttl_seconds
        self._lock = asyncio.Lock()
        self._entries: dict[str, _SessionEntry] = {}
        self._purge_task: asyncio.Task[None] | None = None

    def _purge_expired_unlocked(self) -> None:
        now = time.monotonic()
        dead = [k for k, e in self._entries.items() if now >= e.expires_at]
        for k in dead:
            del self._entries[k]

    async def purge_expired(self) -> None:
        async with self._lock:
            self._purge_expired_unlocked()

    def ensure_periodic_purge_running(self, *, interval_seconds: float = 60.0) -> None:
        if interval_seconds <= 0:
            return
        if self._purge_task is not None and not self._purge_task.done():
            return

        async def _loop() -> None:
            while True:
                await asyncio.sleep(interval_seconds)
                try:
                    await self.purge_expired()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Responses session store periodic purge failed: %s",
                            exc,
                            exc_info=True,
                        )

        self._purge_task = asyncio.create_task(_loop())

    async def stop_periodic_purge(self) -> None:
        if self._purge_task is None:
            return
        self._purge_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._purge_task
        self._purge_task = None

    async def store(
        self,
        response_id: str,
        output_items: list[ResponsesOutputItem],
        ttl_seconds: int | None = None,
        *,
        instructions: str | None = None,
    ) -> None:
        ttl = self._default_ttl_seconds if ttl_seconds is None else ttl_seconds
        expires_at = time.monotonic() + float(ttl)
        async with self._lock:
            self._purge_expired_unlocked()
            self._entries[response_id] = _SessionEntry(
                output_items=list(output_items),
                instructions=instructions,
                expires_at=expires_at,
            )

    async def resolve(
        self, previous_response_id: str
    ) -> ResponsesResolvedSession | None:
        async with self._lock:
            self._purge_expired_unlocked()
            entry = self._entries.get(previous_response_id)
            if entry is None:
                return None
            if time.monotonic() >= entry.expires_at:
                del self._entries[previous_response_id]
                return None
            return ResponsesResolvedSession(
                output_items=list(entry.output_items),
                instructions=entry.instructions,
            )
