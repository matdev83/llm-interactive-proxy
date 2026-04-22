"""Unit tests for InMemoryResponsesSessionStore."""

from __future__ import annotations

import asyncio

import pytest
from src.core.domain.responses_domain import ResponsesOutputItem
from src.core.domain.responses_resolved_session import (
    effective_instructions_for_chained_turn,
)
from src.core.services.in_memory_responses_session_store import (
    InMemoryResponsesSessionStore,
)


def _sample_items() -> list[ResponsesOutputItem]:
    return [
        ResponsesOutputItem(
            id="msg_1",
            type="message",
            role="assistant",
            status="completed",
            content=None,
        )
    ]


@pytest.mark.asyncio
async def test_store_resolve_round_trip() -> None:
    store = InMemoryResponsesSessionStore()
    items = _sample_items()
    await store.store("resp_a", items, ttl_seconds=60, instructions="prior sys")
    resolved = await store.resolve("resp_a")
    assert resolved is not None
    assert list(resolved.output_items) == items
    assert resolved.instructions == "prior sys"


@pytest.mark.asyncio
async def test_resolve_missing_returns_none() -> None:
    store = InMemoryResponsesSessionStore()
    assert await store.resolve("missing") is None


@pytest.mark.asyncio
async def test_purge_expired_removes_stale_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.core.services.in_memory_responses_session_store as store_mod

    class _FakeTime:
        def __init__(self) -> None:
            self.t = 0.0

        def monotonic(self) -> float:
            return self.t

    fake = _FakeTime()
    monkeypatch.setattr(store_mod, "time", fake)

    store = InMemoryResponsesSessionStore(default_ttl_seconds=3600)
    await store.store("resp_x", _sample_items(), ttl_seconds=1, instructions=None)

    fake.t += 2.0
    await store.purge_expired()
    assert await store.resolve("resp_x") is None


@pytest.mark.asyncio
async def test_resolve_expired_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.core.services.in_memory_responses_session_store as store_mod

    class _FakeTime:
        def __init__(self) -> None:
            self.t = 0.0

        def monotonic(self) -> float:
            return self.t

    fake = _FakeTime()
    monkeypatch.setattr(store_mod, "time", fake)

    store = InMemoryResponsesSessionStore(default_ttl_seconds=3600)
    await store.store("resp_x", _sample_items(), ttl_seconds=1, instructions=None)

    assert await store.resolve("resp_x") is not None

    fake.t += 2.0
    assert await store.resolve("resp_x") is None


@pytest.mark.asyncio
async def test_chained_turn_new_instructions_replace_stored_prior() -> None:
    store = InMemoryResponsesSessionStore()
    await store.store(
        "resp_prev",
        _sample_items(),
        ttl_seconds=3600,
        instructions="prior instructions",
    )
    prior = await store.resolve("resp_prev")
    assert prior is not None
    assert (
        effective_instructions_for_chained_turn("replacement", prior.instructions)
        == "replacement"
    )
    assert (
        effective_instructions_for_chained_turn(None, prior.instructions)
        == "prior instructions"
    )


@pytest.mark.asyncio
async def test_concurrent_store_under_lock() -> None:
    store = InMemoryResponsesSessionStore()

    async def write(i: int) -> None:
        await store.store(
            f"id_{i}",
            [
                ResponsesOutputItem(
                    id=f"x{i}",
                    type="message",
                    role="assistant",
                    status="completed",
                )
            ],
            ttl_seconds=3600,
        )

    await asyncio.gather(*(write(i) for i in range(20)))
    for i in range(20):
        r = await store.resolve(f"id_{i}")
        assert r is not None
        assert r.output_items[0].id == f"x{i}"
